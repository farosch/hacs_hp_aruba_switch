"""SSH connection manager for Aruba Switch integration."""
import logging
import asyncio
import paramiko
from typing import Optional, Dict, Any
import time

_LOGGER = logging.getLogger(__name__)

# Global semaphore to limit concurrent SSH connections across all instances
_CONNECTION_SEMAPHORE = asyncio.Semaphore(3)  # Max 3 concurrent SSH connections

class ArubaSSHManager:
    """Manages SSH connections to Aruba switches with connection pooling and retry logic."""
    
    def __init__(self, host: str, username: str, password: str, ssh_port: int = 22):
        self.host = host
        self.username = username
        self.password = password
        self.ssh_port = ssh_port
        self._connection_lock = asyncio.Lock()
        self._last_connection_attempt = 0
        self._connection_backoff = 0.1  # Start with very short backoff
        self._max_backoff = 5  # Reduced max backoff
        self._command_queue = []
        self._processing_queue = False
        
        # Bulk query caching
        self._interface_cache = {}
        self._poe_cache = {}
        self._statistics_cache = {}  # Add statistics cache
        self._link_cache = {}  # Add detailed link status cache
        self._cache_lock = asyncio.Lock()
        self._last_bulk_update = 0
        self._bulk_update_interval = 30  # Bulk update every 30 seconds
        
    async def execute_command(self, command: str, timeout: int = 10) -> Optional[str]:
        """Execute a command on the switch with proper connection management."""
        # Use global semaphore to limit concurrent connections
        async with _CONNECTION_SEMAPHORE:
            # Use the lock directly as an async context manager
            async with self._connection_lock:
                # Minimal backoff to avoid overwhelming
                time_since_last = time.time() - self._last_connection_attempt
                if time_since_last < self._connection_backoff:
                    await asyncio.sleep(self._connection_backoff - time_since_last)
                
                self._last_connection_attempt = time.time()
                
                def _sync_execute():
                    ssh = None
                    try:
                        ssh = paramiko.SSHClient()
                        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                        
                        # Faster connection parameters
                        connect_params = {
                            'hostname': self.host,
                            'username': self.username,
                            'password': self.password,
                            'port': self.ssh_port,
                            'timeout': timeout,
                            'auth_timeout': 5,  # Reduced
                            'banner_timeout': 8,  # Reduced
                            'look_for_keys': False,
                            'allow_agent': False,
                        }
                        
                        # Simplified SSH configs - only try 2 instead of 3
                        ssh_configs = [
                            # Modern SSH
                            {},
                            # Legacy compatibility
                            {
                                'disabled_algorithms': {
                                    'kex': ['diffie-hellman-group14-sha256', 'diffie-hellman-group16-sha512'],
                                    'ciphers': [],
                                    'macs': []
                                }
                            }
                        ]
                        
                        for i, config in enumerate(ssh_configs):
                            try:
                                if ssh:
                                    ssh.close()
                                ssh = paramiko.SSHClient()
                                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                                
                                final_params = {**connect_params, **config}
                                ssh.connect(**final_params)
                                
                                # Use invoke_shell for better switch compatibility
                                shell = ssh.invoke_shell()
                                
                                # Send initial ENTER to activate CLI session
                                shell.send('\n')
                                time.sleep(0.5)  # Wait for prompt
                                
                                # Disable paging to prevent "-- MORE --" prompts
                                shell.send('no page\n')
                                time.sleep(0.5)
                                
                                # Clear any initial output/banner and paging setup response
                                if shell.recv_ready():
                                    shell.recv(4096)
                                
                                # Send the command(s) - handle multi-line commands
                                command_lines = command.split('\n')
                                for i, cmd_line in enumerate(command_lines):
                                    if cmd_line.strip():  # Skip empty lines
                                        _LOGGER.debug(f"Sending command line {i+1}/{len(command_lines)}: {cmd_line.strip()}")
                                        shell.send(cmd_line.strip() + '\n')
                                        time.sleep(0.8)  # Increased delay between commands
                                
                                # Wait for final command execution
                                time.sleep(2)  # Increased final wait
                                
                                # Collect output with pager handling
                                output = ""
                                max_wait = 15  # Maximum wait time
                                start_time = time.time()
                                consecutive_empty_reads = 0
                                
                                while time.time() - start_time < max_wait:
                                    if shell.recv_ready():
                                        chunk = shell.recv(4096).decode('utf-8', errors='ignore')
                                        output += chunk
                                        consecutive_empty_reads = 0
                                        
                                        # Check for pager prompts and handle them
                                        if "-- MORE --" in chunk or "next page: Space" in chunk:
                                            _LOGGER.debug("Detected pager prompt, sending space to continue")
                                            shell.send(' ')  # Send space to continue
                                            time.sleep(0.5)
                                        elif "(q to quit)" in chunk.lower() or "quit: control-c" in chunk.lower():
                                            _LOGGER.debug("Detected quit prompt, sending 'q' to exit pager")
                                            shell.send('q')  # Send 'q' to quit pager
                                            time.sleep(0.5)
                                        
                                        time.sleep(0.1)
                                    else:
                                        consecutive_empty_reads += 1
                                        time.sleep(0.3)
                                        # Break if no data for several consecutive checks
                                        if consecutive_empty_reads >= 5 and output:
                                            break
                                
                                shell.close()
                                
                                # Remove ANSI escape sequences that clutter the output
                                import re
                                ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
                                output = ansi_escape.sub('', output)
                                
                                # Clean up the output (remove command echo, prompts, and pager artifacts)
                                lines = output.split('\n')
                                clean_lines = []
                                for line in lines:
                                    line = line.strip()
                                    # Skip empty lines, command echoes, prompts, and pager artifacts
                                    if (line and 
                                        not line.endswith('#') and 
                                        not line.endswith('>') and
                                        '-- MORE --' not in line and
                                        'next page: Space' not in line and
                                        'quit: Control-C' not in line and
                                        'no page' not in line and
                                        command.replace('\n', ' ').strip() not in line):
                                        clean_lines.append(line)
                                
                                output = '\n'.join(clean_lines)
                                
                                _LOGGER.debug(f"SSH command '{command}' output for {self.host}: {repr(output)}")
                                
                                # Reset backoff on successful connection
                                self._connection_backoff = 0.1
                                return output
                                
                            except (paramiko.SSHException, EOFError, OSError) as e:
                                if i == len(ssh_configs) - 1:  # Last attempt
                                    # Smaller backoff increase
                                    self._connection_backoff = min(self._connection_backoff * 1.5, self._max_backoff)
                                    raise e
                                continue
                        
                        return None
                        
                    except Exception as e:
                        # Smaller backoff increase
                        self._connection_backoff = min(self._connection_backoff * 1.5, self._max_backoff)
                        raise
                    finally:
                        if ssh:
                            try:
                                ssh.close()
                            except:
                                pass
                
                # Run in executor with shorter timeout
                loop = asyncio.get_event_loop()
                try:
                    result = await asyncio.wait_for(
                        loop.run_in_executor(None, _sync_execute), 
                        timeout=timeout + 2
                    )
                    return result
                except asyncio.TimeoutError:
                    _LOGGER.debug(f"SSH command '{command}' timed out for {self.host}")
                    return None
                except Exception as e:
                    _LOGGER.debug(f"SSH command '{command}' failed for {self.host}: {e}")
                    return None

    async def get_all_interface_status(self) -> tuple[dict, dict, dict]:
        """Get status, statistics, and link details for all interfaces in a single query."""
        # Try multiple commands to get interface information
        commands_to_try = [
            "show interface all",
            "show interfaces all",
            "show interface brief",
            "show interfaces brief",
            "show port all",
            "show ports all"
        ]
        
        result = None
        successful_command = None
        
        for cmd in commands_to_try:
            _LOGGER.debug(f"Trying command: {cmd}")
            result = await self.execute_command(cmd, timeout=15)
            if result and len(result.strip()) > 50:  # Got substantial output
                successful_command = cmd
                break
        
        if not result:
            _LOGGER.warning(f"No result from any interface command for {self.host}")
            return {}, {}, {}
        
        _LOGGER.info(f"Successfully used command '{successful_command}' for {self.host}")
        _LOGGER.debug(f"Raw '{successful_command}' output for {self.host} (first 1000 chars): {repr(result[:1000])}")
        
        interfaces = {}
        statistics = {}
        link_details = {}
        current_interface = None
        
        for line in result.split('\n'):
            line = line.strip()
            if not line:
                continue
                
            # Look for interface headers - try multiple patterns
            if ("port counters for port" in line.lower() or 
                "interface" in line.lower() and any(x in line.lower() for x in ["port", "ethernet", "gi", "fa", "te"]) or
                line.lower().startswith("port") or
                ("status and counters" in line.lower() and "port" in line.lower())):
                
                _LOGGER.debug(f"Potential interface header found: {repr(line)}")
                try:
                    # Try multiple extraction methods
                    port_num = None
                    if "port counters for port" in line.lower():
                        port_num = line.split("port")[-1].strip()
                    elif "interface" in line.lower():
                        # Try extracting from interface names like "Interface 1" or "GigabitEthernet1"
                        import re
                        match = re.search(r'(?:interface|port|gi|fa|te)[\s]*(\d+)', line.lower())
                        if match:
                            port_num = match.group(1)
                    elif line.lower().startswith("port"):
                        # Extract from "Port 1" etc
                        import re
                        match = re.search(r'port[\s]*(\d+)', line.lower())
                        if match:
                            port_num = match.group(1)
                    
                    if port_num:
                        current_interface = port_num
                        interfaces[current_interface] = {"port_enabled": False, "link_status": "down"}
                        statistics[current_interface] = {"bytes_in": 0, "bytes_out": 0, "packets_in": 0, "packets_out": 0}
                        link_details[current_interface] = {
                            "link_up": False, "port_enabled": False, "link_speed": "unknown",
                            "duplex": "unknown", "auto_negotiation": "unknown", "cable_type": "unknown"
                        }
                        _LOGGER.debug(f"Successfully parsed interface header for port: {current_interface}")
                    else:
                        _LOGGER.debug(f"Could not extract port number from: {repr(line)}")
                except Exception as e:
                    _LOGGER.debug(f"Failed to parse interface header '{line}': {e}")
                    continue
            elif current_interface:
                line_lower = line.lower()
                _LOGGER.debug(f"Parsing interface line for port {current_interface}: {repr(line)}")
                
                # Check for port enabled/disabled status - handle multiple formats
                if "port enabled" in line_lower or line_lower.strip().startswith("port enabled"):
                    # Look for enabled/disabled or yes/no indicators
                    if ":" in line:
                        value_part = line.split(":", 1)[1].strip().lower()
                        is_enabled = any(pos in value_part for pos in ["yes", "enabled", "up", "active", "true"])
                        interfaces[current_interface]["port_enabled"] = is_enabled
                        link_details[current_interface]["port_enabled"] = is_enabled
                        _LOGGER.debug(f"Found port enabled status for {current_interface}: {is_enabled} (from '{value_part}') - line was: '{line.strip()}'")
                
                # Check for link status
                elif "link status" in line_lower:
                    if ":" in line:
                        value_part = line.split(":", 1)[1].strip().lower()
                        link_up = "up" in value_part
                        interfaces[current_interface]["link_status"] = "up" if link_up else "down"
                        link_details[current_interface]["link_up"] = link_up
                        _LOGGER.debug(f"Found link status for {current_interface}: {'up' if link_up else 'down'} (from '{value_part}')")
                
                # Parse additional link details
                elif "speed" in line_lower and (":" in line or "mbps" in line_lower or "gbps" in line_lower):
                    # Extract speed value
                    import re
                    speed_match = re.search(r'(\d+)\s*(mbps|gbps|mb|gb)', line_lower)
                    if speed_match:
                        speed_val = speed_match.group(1)
                        speed_unit = speed_match.group(2)
                        if "gb" in speed_unit:
                            speed_str = f"{speed_val} Gbps"
                            link_details[current_interface]["link_speed"] = speed_str
                        else:
                            speed_str = f"{speed_val} Mbps"
                            link_details[current_interface]["link_speed"] = speed_str
                        _LOGGER.debug(f"Found link speed for {current_interface}: {speed_str} (from '{line.strip()}')")
                
                elif "duplex" in line_lower:
                    if "full" in line_lower:
                        link_details[current_interface]["duplex"] = "full"
                        _LOGGER.debug(f"Found duplex for {current_interface}: full (from '{line.strip()}')")
                    elif "half" in line_lower:
                        link_details[current_interface]["duplex"] = "half"
                        _LOGGER.debug(f"Found duplex for {current_interface}: half (from '{line.strip()}')")
                
                elif ("auto" in line_lower and "neg" in line_lower) or "autoneg" in line_lower:
                    if ":" in line:
                        value_part = line.split(":", 1)[1].strip().lower()
                        auto_enabled = any(pos in value_part for pos in ["yes", "enabled", "on", "active"])
                        auto_status = "enabled" if auto_enabled else "disabled"
                        link_details[current_interface]["auto_negotiation"] = auto_status
                        _LOGGER.debug(f"Found auto-negotiation for {current_interface}: {auto_status} (from '{value_part}')")
                
                # Parse statistics - handle HP/Aruba format with colons and commas
                elif ":" in line:
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        key = parts[0].strip().lower()
                        value_str = parts[1].strip()
                        
                        # Helper function to extract numbers from comma-separated format
                        def extract_numbers(text):
                            import re
                            # Find all numbers, handling commas as thousands separators
                            numbers = []
                            for match in re.finditer(r'(\d{1,3}(?:,\d{3})*)', text):
                                number_str = match.group(1).replace(',', '')
                                try:
                                    numbers.append(int(number_str))
                                except ValueError:
                                    continue
                            return numbers
                        
                        # Debug what we're trying to parse
                        _LOGGER.debug(f"Parsing line for {current_interface}: key='{key}', value='{value_str}'")
                        
                        # Parse specific statistics formats - Fixed to match actual HP/Aruba output
                        if "bytes rx" in key:
                            # Handle format: "Bytes Rx        : 133,773,022          Bytes Tx        : 82,704,381"
                            # The value_str contains both Rx and Tx values
                            numbers = extract_numbers(value_str)
                            _LOGGER.debug(f"Bytes RX line - extracted numbers: {numbers}")
                            if len(numbers) >= 2:
                                statistics[current_interface]["bytes_in"] = numbers[0]
                                statistics[current_interface]["bytes_out"] = numbers[1]
                                _LOGGER.debug(f"Found bytes for {current_interface}: in={numbers[0]}, out={numbers[1]}")
                            elif len(numbers) == 1:
                                # Single RX value
                                statistics[current_interface]["bytes_in"] = numbers[0]
                                _LOGGER.debug(f"Found bytes_in for {current_interface}: {numbers[0]}")
                        elif "unicast rx" in key:
                            # Handle format: "Unicast Rx      : 178,026              Unicast Tx      : 132,661"
                            numbers = extract_numbers(value_str)
                            _LOGGER.debug(f"Unicast RX line - extracted numbers: {numbers}")
                            if len(numbers) >= 2:
                                statistics[current_interface]["packets_in"] = numbers[0]
                                statistics[current_interface]["packets_out"] = numbers[1]
                                _LOGGER.debug(f"Found unicast packets for {current_interface}: in={numbers[0]}, out={numbers[1]}")
                            elif len(numbers) == 1:
                                # Single RX value
                                statistics[current_interface]["packets_in"] = numbers[0]
                                _LOGGER.debug(f"Found unicast packets_in for {current_interface}: {numbers[0]}")
                        elif "bcast/mcast rx" in key:
                            # Handle broadcast/multicast - add to existing packet counts
                            numbers = extract_numbers(value_str)
                            _LOGGER.debug(f"Bcast/Mcast RX line - extracted numbers: {numbers}")
                            if len(numbers) >= 2:
                                current_in = statistics[current_interface].get("packets_in", 0)
                                current_out = statistics[current_interface].get("packets_out", 0)
                                statistics[current_interface]["packets_in"] = current_in + numbers[0]
                                statistics[current_interface]["packets_out"] = current_out + numbers[1]
                                _LOGGER.debug(f"Added broadcast/multicast packets for {current_interface}: in={numbers[0]}, out={numbers[1]}")
                        elif "bytes" in key and "tx" in key:
                            # Handle separate TX line if it exists
                            numbers = extract_numbers(value_str)
                            if numbers:
                                statistics[current_interface]["bytes_out"] = numbers[0]
                                _LOGGER.debug(f"Found bytes_out for {current_interface}: {numbers[0]}")
                        elif "unicast" in key and "tx" in key:
                            # Handle separate TX line if it exists
                            numbers = extract_numbers(value_str)
                            if numbers:
                                statistics[current_interface]["packets_out"] = numbers[0]
                                _LOGGER.debug(f"Found unicast packets_out for {current_interface}: {numbers[0]}")
                        elif "bytes" in key and len(extract_numbers(value_str)) == 1:
                            # Single value statistics (fallback)
                            numbers = extract_numbers(value_str)
                            if numbers:
                                value = numbers[0]
                                if "rx" in key or "received" in key:
                                    statistics[current_interface]["bytes_in"] = value
                                    _LOGGER.debug(f"Found bytes_in for {current_interface}: {value} (from '{key}: {value_str}')")
                                elif "tx" in key or "transmitted" in key:
                                    statistics[current_interface]["bytes_out"] = value
                                    _LOGGER.debug(f"Found bytes_out for {current_interface}: {value} (from '{key}: {value_str}')")
        
        _LOGGER.debug(f"Parsed {len(interfaces)} interfaces, {len(statistics)} statistics, and {len(link_details)} link details from bulk query")
        
        if not interfaces:
            _LOGGER.warning(f"No interfaces found in '{successful_command}' output for {self.host}! Trying alternative approach.")
            _LOGGER.debug(f"Full output was: {repr(result)}")
            
            # Try alternative method - get statistics separately
            return await self._get_interface_status_alternative()
        
        # Log sample of what was found
        if statistics:
            sample_port = list(statistics.keys())[0]
            sample_stats = statistics[sample_port]
            _LOGGER.debug(f"Sample statistics for port {sample_port}: {sample_stats}")
        else:
            _LOGGER.warning(f"No statistics found in output for {self.host}!")
        
        return interfaces, statistics, link_details

    async def _get_interface_status_alternative(self) -> tuple[dict, dict, dict]:
        """Alternative method to get interface status when main command fails."""
        _LOGGER.info(f"Using alternative interface status method for {self.host}")
        
        interfaces = {}
        statistics = {}
        link_details = {}
        
        # Try to get basic port list first
        port_list_commands = [
            "show interface brief",
            "show interfaces brief", 
            "show port brief",
            "show ports brief",
            "show vlan ports all brief"
        ]
        
        port_result = None
        for cmd in port_list_commands:
            port_result = await self.execute_command(cmd, timeout=10)
            if port_result and "port" in port_result.lower():
                _LOGGER.debug(f"Got port list using '{cmd}': {repr(port_result[:500])}")
                break
        
        # Extract port numbers from the output
        port_numbers = []
        if port_result:
            import re
            # Look for port numbers in various formats
            for match in re.finditer(r'(?:^|\s)(\d+)(?:\s|$|/)', port_result, re.MULTILINE):
                port_num = match.group(1)
                if port_num.isdigit() and 1 <= int(port_num) <= 48:  # Reasonable port range
                    port_numbers.append(port_num)
        
        # If we couldn't extract ports, create a default range
        if not port_numbers:
            _LOGGER.warning(f"Could not extract port numbers for {self.host}, using default range 1-24")
            port_numbers = [str(i) for i in range(1, 25)]
        else:
            # Remove duplicates and sort
            port_numbers = sorted(list(set(port_numbers)), key=int)
            _LOGGER.info(f"Found {len(port_numbers)} ports for {self.host}: {port_numbers[:10]}{'...' if len(port_numbers) > 10 else ''}")
        
        # Initialize empty data for each port
        for port_num in port_numbers:
            interfaces[port_num] = {"port_enabled": False, "link_status": "down"}
            statistics[port_num] = {"bytes_in": 0, "bytes_out": 0, "packets_in": 0, "packets_out": 0}
            link_details[port_num] = {
                "link_up": False, "port_enabled": False, "link_speed": "unknown",
                "duplex": "unknown", "auto_negotiation": "unknown", "cable_type": "unknown"
            }
        
        # Try to get statistics with different commands
        stats_commands = [
            "show interface statistics",
            "show interfaces statistics", 
            "show port statistics",
            "show ports statistics",
            "show interface counters",
            "show interfaces counters"
        ]
        
        for cmd in stats_commands:
            _LOGGER.debug(f"Trying statistics command: {cmd}")
            stats_result = await self.execute_command(cmd, timeout=15)
            if stats_result and len(stats_result.strip()) > 100:
                _LOGGER.debug(f"Got statistics using '{cmd}' (first 800 chars): {repr(stats_result[:800])}")
                
                # Try to parse statistics from this output
                parsed_stats = self._parse_statistics_output(stats_result, port_numbers)
                if parsed_stats:
                    statistics.update(parsed_stats)
                    _LOGGER.info(f"Successfully parsed statistics for {len(parsed_stats)} ports using '{cmd}'")
                    break
        
        return interfaces, statistics, link_details
    
    def _parse_statistics_output(self, output: str, port_numbers: list) -> dict:
        """Parse statistics from various command outputs."""
        stats = {}
        current_port = None
        
        for line in output.split('\n'):
            line = line.strip()
            if not line:
                continue
                
            # Look for port indicators
            for port_num in port_numbers:
                if (f"port {port_num}" in line.lower() or 
                    f"interface {port_num}" in line.lower() or
                    f"gi{port_num}" in line.lower() or
                    line.strip() == port_num):
                    current_port = port_num
                    if current_port not in stats:
                        stats[current_port] = {"bytes_in": 0, "bytes_out": 0, "packets_in": 0, "packets_out": 0}
                    break
            
            if current_port and ":" in line:
                line_lower = line.lower()
                # Parse various statistics formats
                if any(x in line_lower for x in ["bytes", "octets"]):
                    import re
                    numbers = re.findall(r'(\d{1,3}(?:,\d{3})*)', line)
                    if numbers:
                        value = int(numbers[0].replace(',', ''))
                        if "rx" in line_lower or "in" in line_lower or "received" in line_lower:
                            stats[current_port]["bytes_in"] = value
                        elif "tx" in line_lower or "out" in line_lower or "transmitted" in line_lower:
                            stats[current_port]["bytes_out"] = value
                
                elif any(x in line_lower for x in ["packets", "frames"]):
                    import re  
                    numbers = re.findall(r'(\d{1,3}(?:,\d{3})*)', line)
                    if numbers:
                        value = int(numbers[0].replace(',', ''))
                        if "rx" in line_lower or "in" in line_lower or "received" in line_lower:
                            stats[current_port]["packets_in"] = value
                        elif "tx" in line_lower or "out" in line_lower or "transmitted" in line_lower:
                            stats[current_port]["packets_out"] = value
        
        return stats

    async def get_all_poe_status(self) -> dict:
        """Get PoE status for all ports in a single query."""
        # Try different PoE commands based on switch model
        commands = [
            "show power-over-ethernet all",
            "show power-over-ethernet",
            "show poe status",
            "show interface brief power-over-ethernet"
        ]
        
        result = None
        for cmd in commands:
            result = await self.execute_command(cmd, timeout=15)
            if result and "invalid" not in result.lower() and "error" not in result.lower():
                _LOGGER.debug(f"PoE command '{cmd}' succeeded")
                break
            else:
                _LOGGER.debug(f"PoE command '{cmd}' failed or returned error")
        
        if not result:
            _LOGGER.warning("All PoE commands failed")
            return {}
        
        # Log the raw PoE output for debugging
        _LOGGER.debug(f"Raw PoE output:\n{result}")
        
        poe_ports = {}
        current_port = None
        
        for line in result.split('\n'):
            line = line.strip()
            if not line:
                continue
                
            # Look for port headers - handle multiple formats
            port_header_patterns = [
                "information for port",  # "Status and Configuration Information for port X"
                "port status",           # "Port Status X"
                "interface",             # "Interface X" or "Interface GigabitEthernet X"
                "gi",                    # "GigabitEthernet X/X/X" 
                r"^[0-9]+[/]*[0-9]*\s"   # Direct port numbers like "1/1", "24", etc.
            ]
            
            line_lower = line.lower()
            port_found = False
            
            for pattern in port_header_patterns:
                if pattern == r"^[0-9]+[/]*[0-9]*\s":
                    # Handle direct port number lines (regex-like check)
                    import re
                    if re.match(r'^\s*\d+(/\d+)?\s+', line):
                        try:
                            current_port = line.split()[0]
                            poe_ports[current_port] = {"power_enable": False, "poe_status": "off"}
                            _LOGGER.debug(f"Found PoE port header (direct): {current_port}")
                            port_found = True
                            break
                        except:
                            continue
                elif pattern in line_lower:
                    try:
                        if "port" in pattern:
                            port_num = line.split("port")[-1].strip()
                        elif "interface" in pattern:
                            # Handle "Interface X" or "Interface GigabitEthernet X/X/X"
                            parts = line.split()
                            port_num = parts[-1] if parts else ""
                        else:
                            port_num = line.split()[-1] if line.split() else ""
                        
                        if port_num and port_num.replace('/', '').replace('.', '').isdigit():
                            current_port = port_num
                            poe_ports[current_port] = {"power_enable": False, "poe_status": "off"}
                            _LOGGER.debug(f"Found PoE port header ({pattern}): {current_port}")
                            port_found = True
                            break
                    except:
                        continue
            
            if port_found:
                continue
            elif current_port:
                line_lower = line.lower()
                _LOGGER.debug(f"Parsing PoE line for port {current_port}: {repr(line)}")
                
                # Generic handler for combined lines (multiple key:value pairs on one line)
                # This handles HP/Aruba format where multiple fields are on the same line
                def parse_combined_line(line_text):
                    """Parse a line that may contain multiple key:value pairs."""
                    parsed_fields = {}
                    
                    # Split by multiple spaces to find field boundaries
                    import re
                    # Look for pattern: "Key : Value" followed by spaces and another "Key : Value"
                    matches = re.findall(r'([^:]+?)\s*:\s*([^:]*?)(?=\s{3,}[^:]+\s*:|$)', line_text)
                    
                    for key, value in matches:
                        key = key.strip().lower()
                        value = value.strip().lower()
                        parsed_fields[key] = value
                    
                    return parsed_fields
                
                # Parse the line for multiple key:value pairs
                parsed_data = parse_combined_line(line)
                
                # Process each parsed field
                for key, value in parsed_data.items():
                    if "power enable" in key:
                        is_enabled = "yes" in value
                        poe_ports[current_port]["power_enable"] = is_enabled
                        _LOGGER.debug(f"Found PoE power enable for {current_port}: {is_enabled} (from '{value}')")
                    
                    elif "poe port status" in key or "poe status" in key:
                        poe_status_str = "off"  # default
                        
                        if "searching" in value:
                            poe_status_str = "searching"
                        elif "delivering" in value or "deliver" in value:
                            poe_status_str = "delivering"
                        elif "enabled" in value or "on" in value or "active" in value:
                            poe_status_str = "on"
                        elif "disabled" in value or "off" in value or "inactive" in value:
                            poe_status_str = "off"
                        elif "fault" in value or "error" in value or "overload" in value:
                            poe_status_str = "fault"
                        elif "denied" in value or "reject" in value:
                            poe_status_str = "denied"
                        
                        poe_ports[current_port]["poe_status"] = poe_status_str
                        _LOGGER.debug(f"Found PoE status for {current_port}: '{poe_status_str}' (from '{value}')")
                
                # Check for power consumption as additional PoE status indicator
                for key, value in parsed_data.items():
                    if any(keyword in key for keyword in ["power draw", "power consumption", "power usage"]) and "w" in value:
                        import re
                        power_match = re.search(r'(\d+(?:\.\d+)?)\s*w', value)
                        if power_match:
                            power_value = float(power_match.group(1))
                            if power_value > 0:
                                # Override status if we see actual power consumption > 0
                                poe_ports[current_port]["poe_status"] = "delivering" 
                                _LOGGER.debug(f"Found PoE power consumption for {current_port}: {power_value}W - overriding status to 'delivering'")
        
        _LOGGER.debug(f"Parsed {len(poe_ports)} PoE ports from bulk query")
        return poe_ports

    async def update_bulk_cache(self) -> bool:
        """Update the bulk cache with fresh data from the switch."""
        import time
        current_time = time.time()
        
        async with self._cache_lock:
            # Only update if enough time has passed
            if current_time - self._last_bulk_update < self._bulk_update_interval:
                return True  # Cache is still fresh
            
            try:
                # Get interface+statistics and PoE data concurrently
                interface_task = asyncio.create_task(self.get_all_interface_status())
                poe_task = asyncio.create_task(self.get_all_poe_status())
                
                interface_result, self._poe_cache = await asyncio.gather(
                    interface_task, poe_task, return_exceptions=True
                )
                
                # Handle interface result (now returns 3-tuple)
                if isinstance(interface_result, Exception):
                    _LOGGER.warning(f"Failed to update interface cache: {interface_result}")
                    self._interface_cache = {}
                    self._statistics_cache = {}
                    self._link_cache = {}
                    return False
                else:
                    self._interface_cache, self._statistics_cache, self._link_cache = interface_result
                    
                if isinstance(self._poe_cache, Exception):
                    _LOGGER.warning(f"Failed to update PoE cache: {self._poe_cache}")
                    self._poe_cache = {}
                    return False
                
                self._last_bulk_update = current_time
                _LOGGER.debug(f"Updated bulk cache with {len(self._interface_cache)} interfaces, "
                            f"{len(self._statistics_cache)} statistics, {len(self._link_cache)} link details, "
                            f"and {len(self._poe_cache)} PoE ports")
                return True
                
            except Exception as e:
                _LOGGER.error(f"Failed to update bulk cache for {self.host}: {e}")
                return False

    async def force_cache_refresh(self) -> bool:
        """Force an immediate cache refresh, ignoring timeout intervals."""
        async with self._cache_lock:
            self._last_bulk_update = 0  # Reset timestamp to force refresh
        return await self.update_bulk_cache()

    async def get_port_status(self, port: str, is_poe: bool = False) -> dict:
        """Get cached status for a specific port."""
        await self.update_bulk_cache()
        
        async with self._cache_lock:
            if is_poe:
                return self._poe_cache.get(port, {"power_enable": False, "poe_status": False})
            else:
                return self._interface_cache.get(port, {"port_enabled": False, "link_status": "down"})

    async def get_port_statistics(self, port: str) -> dict:
        """Get cached traffic statistics for a specific port."""
        await self.update_bulk_cache()
        
        async with self._cache_lock:
            cached_stats = self._statistics_cache.get(port, {
                "bytes_in": 0,
                "bytes_out": 0,
                "packets_in": 0,
                "packets_out": 0
            })
            
            _LOGGER.debug(f"Retrieved cached statistics for port {port}: {cached_stats}")
            _LOGGER.debug(f"Statistics cache contains {len(self._statistics_cache)} ports: {list(self._statistics_cache.keys())}")
            
            return cached_stats

    async def get_port_link_status(self, port: str) -> dict:
        """Get cached detailed link status information for a specific port."""
        await self.update_bulk_cache()
        
        async with self._cache_lock:
            cached_link = self._link_cache.get(port, {
                "link_up": False,
                "port_enabled": False,
                "link_speed": "unknown",
                "duplex": "unknown", 
                "auto_negotiation": "unknown",
                "cable_type": "unknown"
            })
            
            _LOGGER.debug(f"Retrieved cached link status for port {port}: {cached_link}")
            _LOGGER.debug(f"Link cache contains {len(self._link_cache)} ports: {list(self._link_cache.keys())}")
            
            return cached_link

# Global connection managers
_connection_managers: Dict[str, ArubaSSHManager] = {}

def get_ssh_manager(host: str, username: str, password: str, ssh_port: int = 22) -> ArubaSSHManager:
    """Get or create an SSH manager for the given host."""
    key = f"{host}:{ssh_port}"
    if key not in _connection_managers:
        _connection_managers[key] = ArubaSSHManager(host, username, password, ssh_port)
    return _connection_managers[key]