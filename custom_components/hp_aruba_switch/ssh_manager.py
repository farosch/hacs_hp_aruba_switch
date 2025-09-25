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
        # Use the standard interface all command
        cmd = "show interface all"
        
        _LOGGER.debug(f"Executing interface command: {cmd}")
        result = await self.execute_command(cmd, timeout=15)
        
        if not result or len(result.strip()) <= 50:
            _LOGGER.warning(f"Interface command '{cmd}' failed for {self.host}")
            return {}, {}, {}
        
        _LOGGER.info(f"Successfully executed '{cmd}' for {self.host}")
        _LOGGER.debug(f"Raw '{cmd}' output for {self.host} (first 1000 chars): {repr(result[:1000])}")
        
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
            _LOGGER.warning(f"No interfaces found in '{cmd}' output for {self.host}! Trying alternative approach.")
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

    async def get_interface_brief_info(self) -> dict:
        """Get interface brief information for speed/duplex data."""
        # Use the standard interface brief command
        cmd = "show interface brief"
        
        _LOGGER.debug(f"Executing brief command: {cmd}")
        result = await self.execute_command(cmd, timeout=10)
        
        if not result or "port" not in result.lower() or len(result.strip()) <= 100:
            _LOGGER.warning(f"Interface brief command failed for {self.host}")
            return {}
        
        _LOGGER.info(f"Successfully executed '{cmd}' for {self.host}")
        _LOGGER.debug(f"Raw brief output (first 800 chars): {repr(result[:800])}")
        
        brief_info = {}
        
        # Parse the tabular output
        lines = result.split('\n')
        in_port_section = False
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Look for the header line to start parsing
            if "port" in line.lower() and ("type" in line.lower() or "status" in line.lower()):
                in_port_section = True
                continue
            elif line.startswith("-") or line.startswith("="):
                # Skip separator lines
                continue
            elif not in_port_section:
                continue
            
            # Parse port data lines
            # Expected format: Port Type | Alert Enabled Status Mode MDI Flow
            # Example: "1     100/1000T  | No        Yes     Up     1000FDx    MDIX off"
            
            if "|" in line:
                parts = line.split("|")
                if len(parts) >= 2:
                    left_part = parts[0].strip()
                    right_part = parts[1].strip()
                    
                    # Extract port number from left part
                    port_match = left_part.split()
                    if port_match:
                        try:
                            port_num = port_match[0]
                            
                            # Parse right part: "No Yes Up 1000FDx MDIX off"
                            right_fields = right_part.split()
                            if len(right_fields) >= 4:
                                # Fields: [Alert, Enabled, Status, Mode, MDI, Flow]
                                alert = right_fields[0]
                                enabled = right_fields[1]
                                status = right_fields[2] 
                                mode = right_fields[3]
                                
                                # Parse speed and duplex from mode (e.g., "1000FDx")
                                speed_mbps = 0
                                duplex = "unknown"
                                
                                if mode and mode != ".":
                                    import re
                                    # Match patterns like "1000FDx", "100HDx", "10FDx"
                                    speed_match = re.match(r'(\d+)(FD|HD|F|H)?x?', mode)
                                    if speed_match:
                                        speed_mbps = int(speed_match.group(1))
                                        duplex_code = speed_match.group(2)
                                        if duplex_code:
                                            if duplex_code.startswith('F'):
                                                duplex = "full"
                                            elif duplex_code.startswith('H'):
                                                duplex = "half"
                                
                                brief_info[port_num] = {
                                    "port_enabled": enabled.lower() == "yes",
                                    "link_up": status.lower() == "up",
                                    "link_speed_mbps": speed_mbps,
                                    "duplex": duplex,
                                    "mode": mode,
                                    "mdi": right_fields[4] if len(right_fields) > 4 else "unknown"
                                }
                                
                                _LOGGER.debug(f"Parsed brief info for port {port_num}: speed={speed_mbps}Mbps, duplex={duplex}, enabled={enabled}, status={status}")
                        
                        except (ValueError, IndexError) as e:
                            _LOGGER.debug(f"Could not parse brief line: {repr(line)} - {e}")
                            continue
        
        # If tabular parsing failed, try alternative port extraction
        if not brief_info and result:
            _LOGGER.debug(f"Tabular parsing failed, trying alternative port extraction from brief output")
            import re
            # Look for port numbers in various formats as fallback
            for match in re.finditer(r'(?:^|\s)(\d+)(?:\s|$|/)', result, re.MULTILINE):
                port_num = match.group(1)
                if port_num.isdigit() and 1 <= int(port_num) <= 48:  # Reasonable port range
                    if port_num not in brief_info:
                        brief_info[port_num] = {
                            "port_enabled": True,  # Default assumption
                            "link_up": False,      # Default assumption
                            "link_speed_mbps": 0,
                            "duplex": "unknown",
                            "mode": "unknown",
                            "mdi": "unknown"
                        }
            _LOGGER.debug(f"Alternative extraction found {len(brief_info)} ports")
        
        _LOGGER.debug(f"Parsed brief info for {len(brief_info)} ports")
        return brief_info

    async def _get_interface_status_alternative(self) -> tuple[dict, dict, dict]:
        """Alternative method to get interface status when main command fails."""
        _LOGGER.info(f"Using alternative interface status method for {self.host}")
        
        interfaces = {}
        statistics = {}
        link_details = {}
        
        # Use the existing brief info method instead of duplicating commands
        brief_info = await self.get_interface_brief_info()
        
        if brief_info:
            # Extract port numbers and basic info from brief data
            port_numbers = list(brief_info.keys())
            _LOGGER.info(f"Found {len(port_numbers)} ports from brief info for {self.host}: {port_numbers[:10]}{'...' if len(port_numbers) > 10 else ''}")
            
            # Initialize data using brief info
            for port_num in port_numbers:
                port_data = brief_info[port_num]
                interfaces[port_num] = {
                    "port_enabled": port_data.get("port_enabled", False),
                    "link_status": "up" if port_data.get("link_up", False) else "down"
                }
                statistics[port_num] = {"bytes_in": 0, "bytes_out": 0, "packets_in": 0, "packets_out": 0}
                link_details[port_num] = {
                    "link_up": port_data.get("link_up", False),
                    "port_enabled": port_data.get("port_enabled", False),
                    "link_speed": f"{port_data['link_speed_mbps']} Mbps" if port_data.get("link_speed_mbps", 0) > 0 else "unknown",
                    "duplex": port_data.get("duplex", "unknown"),
                    "auto_negotiation": "unknown",
                    "cable_type": "unknown",
                    "mode": port_data.get("mode", "unknown"),
                    "mdi": port_data.get("mdi", "unknown")
                }
        else:
            # Fallback to default port range if brief info fails
            _LOGGER.warning(f"Brief info failed for {self.host}, using default range 1-24")
            port_numbers = [str(i) for i in range(1, 25)]
            
            # Initialize empty data for each port
            for port_num in port_numbers:
                interfaces[port_num] = {"port_enabled": False, "link_status": "down"}
                statistics[port_num] = {"bytes_in": 0, "bytes_out": 0, "packets_in": 0, "packets_out": 0}
                link_details[port_num] = {
                    "link_up": False, "port_enabled": False, "link_speed": "unknown",
                    "duplex": "unknown", "auto_negotiation": "unknown", "cable_type": "unknown"
                }
        
        # Statistics are not available via separate commands on HP/Aruba switches
        # They are obtained through the main interface status commands only
        _LOGGER.debug(f"Alternative method initialized {len(port_numbers)} ports with zero statistics")
        
        return interfaces, statistics, link_details

    async def get_all_poe_status(self) -> dict:
        """Get PoE status for all ports in a single query."""
        # Use the standard PoE command
        cmd = "show power-over-ethernet all"
        
        _LOGGER.debug(f"Executing PoE command: {cmd}")
        result = await self.execute_command(cmd, timeout=15)
        
        if not result or "invalid" in result.lower() or "error" in result.lower():
            _LOGGER.warning(f"PoE command '{cmd}' failed or returned error")
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

    async def get_all_switch_data(self) -> tuple[dict, dict, dict, dict]:
        """Execute all commands in a single SSH session and parse the combined output."""
        # Define all commands we need to execute
        commands = [
            "show interface all",
            "show interface brief", 
            "show power-over-ethernet all"
        ]
        
        # Combine all commands into a single multi-line command
        combined_command = "\n".join(commands)
        
        _LOGGER.debug(f"Executing combined commands in single session: {commands}")
        result = await self.execute_command(combined_command, timeout=30)
        
        if not result:
            _LOGGER.warning(f"Combined command execution failed for {self.host}")
            return {}, {}, {}, {}
        
        _LOGGER.info(f"Successfully executed {len(commands)} commands in single session for {self.host}")
        _LOGGER.debug(f"Combined output length: {len(result)} characters")
        
        # Parse the combined output
        return self._parse_combined_output(result, commands)
    
    def _parse_combined_output(self, output: str, commands: list) -> tuple[dict, dict, dict, dict]:
        """Parse the combined output from all commands."""
        interfaces = {}
        statistics = {}
        link_details = {}
        poe_ports = {}
        
        # Split output by command boundaries - look for command echoes or patterns
        sections = self._split_output_by_commands(output, commands)
        
        for i, (cmd, section_output) in enumerate(sections.items()):
            _LOGGER.debug(f"Processing section for command '{cmd}' (length: {len(section_output)})")
            
            if "show interface all" in cmd:
                # Parse interface status and statistics
                ifaces, stats, links = self._parse_interface_all_output(section_output)
                interfaces.update(ifaces)
                statistics.update(stats)
                link_details.update(links)
                
            elif "show interface brief" in cmd:
                # Parse brief interface info
                brief_info = self._parse_interface_brief_output(section_output)
                # Merge brief info into link_details
                for port, info in brief_info.items():
                    if port in link_details:
                        # Update existing link details with brief info
                        link_details[port].update({
                            "link_speed": f"{info['link_speed_mbps']} Mbps" if info['link_speed_mbps'] > 0 else "unknown",
                            "duplex": info["duplex"],
                            "link_up": info["link_up"],
                            "port_enabled": info["port_enabled"],
                            "mode": info.get("mode", "unknown"),
                            "mdi": info.get("mdi", "unknown")
                        })
                    else:
                        # Create new link details entry
                        link_details[port] = {
                            "link_up": info["link_up"],
                            "port_enabled": info["port_enabled"],
                            "link_speed": f"{info['link_speed_mbps']} Mbps" if info['link_speed_mbps'] > 0 else "unknown",
                            "duplex": info["duplex"],
                            "auto_negotiation": "unknown",
                            "cable_type": "unknown",
                            "mode": info.get("mode", "unknown"),
                            "mdi": info.get("mdi", "unknown")
                        }
                        
            elif "show power-over-ethernet all" in cmd:
                # Parse PoE status
                poe_ports.update(self._parse_poe_output(section_output))
        
        _LOGGER.debug(f"Parsed from combined output: {len(interfaces)} interfaces, {len(statistics)} statistics, "
                     f"{len(link_details)} link details, {len(poe_ports)} PoE ports")
        
        return interfaces, statistics, link_details, poe_ports
    
    def _split_output_by_commands(self, output: str, commands: list) -> dict:
        """Split the combined output into sections for each command."""
        sections = {}
        current_section = ""
        current_command = None
        
        lines = output.split('\n')
        
        for line in lines:
            line_stripped = line.strip()
            
            # Check if this line matches any of our commands (command echo)
            matching_cmd = None
            for cmd in commands:
                if cmd.strip() in line_stripped:
                    matching_cmd = cmd
                    break
            
            if matching_cmd:
                # Save previous section if we have one
                if current_command and current_section:
                    sections[current_command] = current_section.strip()
                
                # Start new section
                current_command = matching_cmd
                current_section = ""
                _LOGGER.debug(f"Found command boundary for: {matching_cmd}")
            else:
                # Add line to current section
                if current_command:
                    current_section += line + "\n"
        
        # Save the last section
        if current_command and current_section:
            sections[current_command] = current_section.strip()
        
        # If splitting by command echo failed, try to split by output patterns
        if not sections:
            _LOGGER.debug("Command echo splitting failed, trying pattern-based splitting")
            sections = self._split_by_output_patterns(output, commands)
        
        return sections
    
    def _split_by_output_patterns(self, output: str, commands: list) -> dict:
        """Alternative splitting method based on output patterns."""
        sections = {}
        
        # Simple approach: split the output into roughly equal parts
        lines = output.split('\n')
        total_lines = len(lines)
        
        if total_lines < 10:  # Too short to split meaningfully
            sections[commands[0]] = output
            return sections
        
        # Rough estimation: divide output by number of commands
        lines_per_cmd = total_lines // len(commands)
        
        for i, cmd in enumerate(commands):
            start_line = i * lines_per_cmd
            if i == len(commands) - 1:  # Last command gets remaining lines
                end_line = total_lines
            else:
                end_line = (i + 1) * lines_per_cmd
            
            section_lines = lines[start_line:end_line]
            sections[cmd] = '\n'.join(section_lines)
            _LOGGER.debug(f"Pattern-based split for '{cmd}': lines {start_line}-{end_line}")
        
        return sections
    
    def _parse_interface_all_output(self, output: str) -> tuple[dict, dict, dict]:
        """Parse 'show interface all' output for interfaces, statistics, and link details."""
        interfaces = {}
        statistics = {}
        link_details = {}
        current_interface = None
        
        for line in output.split('\n'):
            line = line.strip()
            if not line:
                continue
                
            # Look for interface headers - try multiple patterns
            if ("port counters for port" in line.lower() or 
                "interface" in line.lower() and any(x in line.lower() for x in ["port", "ethernet", "gi", "fa", "te"]) or
                line.lower().startswith("port") or
                ("status and counters" in line.lower() and "port" in line.lower())):
                
                try:
                    # Try multiple extraction methods
                    port_num = None
                    if "port counters for port" in line.lower():
                        port_num = line.split("port")[-1].strip()
                    elif "interface" in line.lower():
                        import re
                        match = re.search(r'(?:interface|port|gi|fa|te)[\s]*(\d+)', line.lower())
                        if match:
                            port_num = match.group(1)
                    elif line.lower().startswith("port"):
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
                except Exception as e:
                    continue
                    
            elif current_interface:
                line_lower = line.lower()
                
                # Parse port status, link details, and statistics using existing logic
                if "port enabled" in line_lower and ":" in line:
                    value_part = line.split(":", 1)[1].strip().lower()
                    is_enabled = any(pos in value_part for pos in ["yes", "enabled", "up", "active", "true"])
                    interfaces[current_interface]["port_enabled"] = is_enabled
                    link_details[current_interface]["port_enabled"] = is_enabled
                
                elif "link status" in line_lower and ":" in line:
                    value_part = line.split(":", 1)[1].strip().lower()
                    link_up = "up" in value_part
                    interfaces[current_interface]["link_status"] = "up" if link_up else "down"
                    link_details[current_interface]["link_up"] = link_up
                
                elif ":" in line:
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        key = parts[0].strip().lower()
                        value_str = parts[1].strip()
                        
                        # Extract statistics using existing logic
                        def extract_numbers(text):
                            import re
                            numbers = []
                            for match in re.finditer(r'(\d{1,3}(?:,\d{3})*)', text):
                                number_str = match.group(1).replace(',', '')
                                try:
                                    numbers.append(int(number_str))
                                except ValueError:
                                    continue
                            return numbers
                        
                        if "bytes rx" in key:
                            numbers = extract_numbers(value_str)
                            if len(numbers) >= 2:
                                statistics[current_interface]["bytes_in"] = numbers[0]
                                statistics[current_interface]["bytes_out"] = numbers[1]
                            elif len(numbers) == 1:
                                statistics[current_interface]["bytes_in"] = numbers[0]
                        elif "unicast rx" in key:
                            numbers = extract_numbers(value_str)
                            if len(numbers) >= 2:
                                statistics[current_interface]["packets_in"] = numbers[0]
                                statistics[current_interface]["packets_out"] = numbers[1]
                            elif len(numbers) == 1:
                                statistics[current_interface]["packets_in"] = numbers[0]
        
        return interfaces, statistics, link_details
    
    def _parse_interface_brief_output(self, output: str) -> dict:
        """Parse 'show interface brief' output for speed/duplex data."""
        brief_info = {}
        lines = output.split('\n')
        in_port_section = False
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Look for the header line to start parsing
            if "port" in line.lower() and ("type" in line.lower() or "status" in line.lower()):
                in_port_section = True
                continue
            elif line.startswith("-") or line.startswith("="):
                continue
            elif not in_port_section:
                continue
            
            # Parse port data lines
            if "|" in line:
                parts = line.split("|")
                if len(parts) >= 2:
                    left_part = parts[0].strip()
                    right_part = parts[1].strip()
                    
                    port_match = left_part.split()
                    if port_match:
                        try:
                            port_num = port_match[0]
                            right_fields = right_part.split()
                            if len(right_fields) >= 4:
                                enabled = right_fields[1]
                                status = right_fields[2] 
                                mode = right_fields[3]
                                
                                speed_mbps = 0
                                duplex = "unknown"
                                
                                if mode and mode != ".":
                                    import re
                                    speed_match = re.match(r'(\d+)(FD|HD|F|H)?x?', mode)
                                    if speed_match:
                                        speed_mbps = int(speed_match.group(1))
                                        duplex_code = speed_match.group(2)
                                        if duplex_code:
                                            if duplex_code.startswith('F'):
                                                duplex = "full"
                                            elif duplex_code.startswith('H'):
                                                duplex = "half"
                                
                                brief_info[port_num] = {
                                    "port_enabled": enabled.lower() == "yes",
                                    "link_up": status.lower() == "up",
                                    "link_speed_mbps": speed_mbps,
                                    "duplex": duplex,
                                    "mode": mode,
                                    "mdi": right_fields[4] if len(right_fields) > 4 else "unknown"
                                }
                        except (ValueError, IndexError):
                            continue
        
        return brief_info
    
    def _parse_poe_output(self, output: str) -> dict:
        """Parse 'show power-over-ethernet all' output for PoE status."""
        poe_ports = {}
        current_port = None
        
        for line in output.split('\n'):
            line = line.strip()
            if not line:
                continue
                
            # Look for port headers
            port_header_patterns = [
                "information for port", "port status", "interface", "gi", r"^[0-9]+[/]*[0-9]*\s"
            ]
            
            line_lower = line.lower()
            port_found = False
            
            for pattern in port_header_patterns:
                if pattern == r"^[0-9]+[/]*[0-9]*\s":
                    import re
                    if re.match(r'^\s*\d+(/\d+)?\s+', line):
                        try:
                            current_port = line.split()[0]
                            poe_ports[current_port] = {"power_enable": False, "poe_status": "off"}
                            port_found = True
                            break
                        except:
                            continue
                elif pattern in line_lower:
                    try:
                        if "port" in pattern:
                            port_num = line.split("port")[-1].strip()
                        elif "interface" in pattern:
                            parts = line.split()
                            port_num = parts[-1] if parts else ""
                        else:
                            port_num = line.split()[-1] if line.split() else ""
                        
                        if port_num and port_num.replace('/', '').replace('.', '').isdigit():
                            current_port = port_num
                            poe_ports[current_port] = {"power_enable": False, "poe_status": "off"}
                            port_found = True
                            break
                    except:
                        continue
            
            if port_found:
                continue
            elif current_port:
                # Parse PoE data for current port using existing logic
                def parse_combined_line(line_text):
                    parsed_fields = {}
                    import re
                    matches = re.findall(r'([^:]+?)\s*:\s*([^:]*?)(?=\s{3,}[^:]+\s*:|$)', line_text)
                    for key, value in matches:
                        key = key.strip().lower()
                        value = value.strip().lower()
                        parsed_fields[key] = value
                    return parsed_fields
                
                parsed_data = parse_combined_line(line)
                
                for key, value in parsed_data.items():
                    if "power enable" in key:
                        is_enabled = "yes" in value
                        poe_ports[current_port]["power_enable"] = is_enabled
                    elif "poe port status" in key or "poe status" in key:
                        poe_status_str = "off"
                        if "searching" in value:
                            poe_status_str = "searching"
                        elif "delivering" in value or "deliver" in value:
                            poe_status_str = "delivering"
                        elif "enabled" in value or "on" in value or "active" in value:
                            poe_status_str = "on"
                        elif "fault" in value or "error" in value or "overload" in value:
                            poe_status_str = "fault"
                        elif "denied" in value or "reject" in value:
                            poe_status_str = "denied"
                        poe_ports[current_port]["poe_status"] = poe_status_str
        
        return poe_ports

    async def update_bulk_cache(self) -> bool:
        """Update the bulk cache with fresh data from the switch using single session."""
        import time
        current_time = time.time()
        
        async with self._cache_lock:
            # Only update if enough time has passed
            if current_time - self._last_bulk_update < self._bulk_update_interval:
                return True  # Cache is still fresh
            
            try:
                # Execute all commands in a single session
                interfaces, statistics, link_details, poe_ports = await self.get_all_switch_data()
                
                # Update all caches
                self._interface_cache = interfaces
                self._statistics_cache = statistics  
                self._link_cache = link_details
                self._poe_cache = poe_ports
                
                self._last_bulk_update = current_time
                _LOGGER.debug(f"Updated bulk cache via single session: {len(interfaces)} interfaces, "
                            f"{len(statistics)} statistics, {len(link_details)} link details, "
                            f"{len(poe_ports)} PoE ports")
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