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
        self._max_backoff = 5.0  # Maximum backoff in seconds
        
        # Simple availability tracking
        self._is_available = True
        self._last_successful_connection = 0
        
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
                            except Exception as e:
                                _LOGGER.debug(f"Error closing SSH connection: {e}")
                
                # Run in executor with shorter timeout
                loop = asyncio.get_event_loop()
                try:
                    result = await asyncio.wait_for(
                        loop.run_in_executor(None, _sync_execute), 
                        timeout=timeout + 2
                    )
                    
                    # Update availability on successful command execution
                    if result is not None:
                        was_offline = not self._is_available
                        self._is_available = True
                        self._last_successful_connection = time.time()
                        if was_offline:
                            _LOGGER.info(f"Switch {self.host} is back online")
                    else:
                        was_online = self._is_available
                        self._is_available = False
                        if was_online:
                            _LOGGER.warning(f"Switch {self.host} went offline (command returned no data)")
                            
                    return result
                except asyncio.TimeoutError:
                    _LOGGER.debug(f"SSH command '{command}' timed out for {self.host}")
                    was_online = self._is_available
                    self._is_available = False
                    if was_online:
                        _LOGGER.warning(f"Switch {self.host} went offline (timeout)")
                    return None
                except Exception as e:
                    _LOGGER.debug(f"SSH command '{command}' failed for {self.host}: {e}")
                    was_online = self._is_available
                    self._is_available = False
                    if was_online:
                        _LOGGER.warning(f"Switch {self.host} went offline (connection error: {e})")
                    return None


    async def get_all_switch_data(self) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
        """Execute all commands sequentially and parse each output independently.
        
        Each SSH command is executed individually and its output is sent to a dedicated parser.
        This makes parsing logic cleaner and easier to test.
        
        Returns:
            Tuple of (interfaces, statistics, link_details, poe_ports, version_info) dictionaries.
        """
        commands = {
            "show interface all": self.parse_show_interface_all,
            "show interface brief": self.parse_show_interface_brief,
            "show power-over-ethernet all": self.parse_show_power_over_ethernet_all,
            "show version": self.parse_show_version,
        }

        interfaces: Dict[str, Any] = {}
        statistics: Dict[str, Any] = {}
        link_details: Dict[str, Any] = {}
        poe_ports: Dict[str, Any] = {}
        version_info: Dict[str, Any] = {}

        # Execute each command and parse its output independently
        for cmd, parser in commands.items():
            _LOGGER.debug(f"📋 Executing command '{cmd}' for {self.host}")
            try:
                output = await self.execute_command(cmd, timeout=20)
            except Exception as err:
                _LOGGER.error(f"❌ Command '{cmd}' failed for {self.host}: {err}")
                continue

            if not output:
                _LOGGER.warning(f"⚠️ Command '{cmd}' returned no data for {self.host}")
                continue

            # Parse the output using the dedicated parser
            try:
                loop = asyncio.get_event_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, parser, output),
                    timeout=10.0,
                )
                
                # Merge results based on command type
                if cmd == "show interface all":
                    ifaces, stats, links = result
                    interfaces.update(ifaces)
                    statistics.update(stats)
                    link_details.update(links)
                    _LOGGER.debug(f"✅ Parsed interface all: {len(ifaces)} interfaces, {len(stats)} stats, {len(links)} links")
                    
                elif cmd == "show interface brief":
                    brief_info = result
                    # Merge brief info (speed/duplex) into link_details
                    for port, info in brief_info.items():
                        if port in link_details:
                            link_details[port].update({
                                "link_speed": f"{info['link_speed_mbps']} Mbps" if info['link_speed_mbps'] > 0 else "unknown",
                                "duplex": info["duplex"],
                                "mode": info.get("mode", "unknown"),
                                "mdi": info.get("mdi", "unknown"),
                            })
                        else:
                            link_details[port] = {
                                "link_up": False,
                                "port_enabled": False,
                                "link_speed": f"{info['link_speed_mbps']} Mbps" if info['link_speed_mbps'] > 0 else "unknown",
                                "duplex": info["duplex"],
                                "auto_negotiation": "unknown",
                                "cable_type": "unknown",
                                "mode": info.get("mode", "unknown"),
                                "mdi": info.get("mdi", "unknown"),
                            }
                    _LOGGER.debug(f"✅ Parsed interface brief: {len(brief_info)} interfaces")
                    
                elif cmd == "show power-over-ethernet all":
                    poe_ports.update(result)
                    _LOGGER.debug(f"✅ Parsed PoE: {len(result)} ports")
                    
                elif cmd == "show version":
                    version_info.update(result)
                    _LOGGER.debug(f"✅ Parsed version: {bool(result)}")
                    
            except asyncio.TimeoutError:
                _LOGGER.error(f"❌ Parsing timed out for command '{cmd}' on {self.host}")
            except Exception as err:
                _LOGGER.error(f"❌ Parsing failed for command '{cmd}' on {self.host}: {err}")

        if any([interfaces, statistics, link_details, poe_ports, version_info]):
            _LOGGER.info(
                "✅ Data collection succeeded for %s (interfaces=%d, stats=%d, links=%d, poe=%d, version=%s)",
                self.host,
                len(interfaces),
                len(statistics),
                len(link_details),
                len(poe_ports),
                bool(version_info),
            )
            return interfaces, statistics, link_details, poe_ports, version_info

        _LOGGER.error(f"❌ No usable data collected from {self.host}")
        return {}, {}, {}, {}, {}
    
    
    def parse_show_interface_all(self, output: str) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        """Parse 'show interface all' output for interfaces, statistics, and link details.
        
        Args:
            output: Raw output from 'show interface all' command
            
        Returns:
            Tuple of (interfaces, statistics, link_details) dictionaries.
        """
        interfaces: dict[str, dict] = {}
        statistics: dict[str, dict] = {}
        link_details: dict[str, dict] = {}
        current_interface: str | None = None
        in_totals_section = False
        in_errors_section = False
        in_others_section = False
        in_rates_section = False

        for raw_line in output.split('\n'):
            line = raw_line.strip()
            if not line:
                in_totals_section = False
                in_errors_section = False
                in_others_section = False
                in_rates_section = False
                continue

            line_lower = line.lower()

            # Look for interface headers - try multiple patterns
            if (
                "port counters for port" in line_lower
                or ("interface" in line_lower and any(x in line_lower for x in ["port", "ethernet", "gi", "fa", "te"]))
                or (line_lower.startswith("port") and "port counters" in line_lower)
                or ("status and counters" in line_lower and "port" in line_lower)
            ):
                try:
                    port_num = None
                    if "port counters for port" in line_lower:
                        port_num = line.split("port")[-1].strip()
                    elif "interface" in line_lower:
                        import re

                        match = re.search(r"(?:interface|port|gi|fa|te)[\s]*(\d+)", line_lower)
                        if match:
                            port_num = match.group(1)
                    elif line_lower.startswith("port"):
                        import re

                        match = re.search(r"port[\s]*(\d+)", line_lower)
                        if match:
                            port_num = match.group(1)

                    if port_num:
                        current_interface = port_num
                        interfaces[current_interface] = {
                            "port_enabled": False,
                            "link_status": "down",
                            "mac_address": "unknown",
                            "name": ""
                        }
                        statistics[current_interface] = {
                            "bytes_in": 0,
                            "bytes_out": 0,
                            "packets_in": 0,
                            "packets_out": 0,
                            "bytes_rx": 0,
                            "bytes_tx": 0,
                            "unicast_rx": 0,
                            "unicast_tx": 0,
                            "bcast_mcast_rx": 0,
                            "bcast_mcast_tx": 0,
                            # Error counters
                            "fcs_rx": 0,
                            "drops_tx": 0,
                            "alignment_rx": 0,
                            "collisions_tx": 0,
                            "runts_rx": 0,
                            "late_colln_tx": 0,
                            "giants_rx": 0,
                            "excessive_colln": 0,
                            "total_rx_errors": 0,
                            "deferred_tx": 0,
                            # Other counters
                            "discard_rx": 0,
                            "out_queue_len": 0,
                            "unknown_protos": 0,
                            # Rates (5 minute averages)
                            "total_rx_bps": 0,
                            "total_tx_bps": 0,
                            "unicast_rx_pps": 0,
                            "unicast_tx_pps": 0,
                            "bcast_mcast_rx_pps": 0,
                            "bcast_mcast_tx_pps": 0,
                            "utilization_rx_percent": 0.0,
                            "utilization_tx_percent": 0.0,
                        }
                        link_details[current_interface] = {
                            "link_up": False,
                            "port_enabled": False,
                            "link_speed": "unknown",
                            "duplex": "unknown",
                        }
                        _LOGGER.debug(f"Started parsing port {current_interface} from line: '{line}'")
                        in_totals_section = False
                        in_errors_section = False
                        in_others_section = False
                        in_rates_section = False
                except Exception:
                    continue

                continue

            if current_interface is None:
                continue

            # Track which section of the output we're parsing
            if "totals (since boot" in line_lower:
                in_totals_section = True
                in_errors_section = False
                in_others_section = False
                in_rates_section = False
                continue
            elif "errors (since boot" in line_lower:
                in_totals_section = False
                in_errors_section = True
                in_others_section = False
                in_rates_section = False
                continue
            elif "others (since boot" in line_lower:
                in_totals_section = False
                in_errors_section = False
                in_others_section = True
                in_rates_section = False
                continue
            elif "rates (" in line_lower:
                in_totals_section = False
                in_errors_section = False
                in_others_section = False
                in_rates_section = True
                continue

            # Parse port status, link details, and statistics
            import re

            if "enabled" in line_lower:
                _LOGGER.debug(
                    f"Port {current_interface}: DEBUG - Line contains 'enabled': '{line}' (repr: {repr(line)})"
                )

            normalized_line = re.sub(r"\s+", " ", line_lower.strip())
            
            # Port enabled status
            if ("port enabled :" in normalized_line) or ("port enabled:" in normalized_line):
                value_part = line.split(":", 1)[1].strip().lower()
                is_enabled = any(pos in value_part for pos in ["yes", "enabled", "up", "active", "true"])
                interfaces[current_interface]["port_enabled"] = is_enabled
                link_details[current_interface]["port_enabled"] = is_enabled
                _LOGGER.debug(
                    f"Port {current_interface}: Found 'Port Enabled' line: '{line}' -> value_part: '{value_part}' -> is_enabled: {is_enabled}"
                )
                continue

            # Link status
            if ("link status :" in normalized_line) or ("link status:" in normalized_line):
                value_part = line.split(":", 1)[1].strip().lower()
                link_up = "up" in value_part
                interfaces[current_interface]["link_status"] = "up" if link_up else "down"
                link_details[current_interface]["link_up"] = link_up
                _LOGGER.debug(
                    f"Port {current_interface}: Found 'Link Status' line: '{line}' -> value_part: '{value_part}' -> link_up: {link_up}"
                )
                continue

            # MAC Address
            if "mac address" in normalized_line and ":" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    mac_address = parts[1].strip()
                    interfaces[current_interface]["mac_address"] = mac_address
                    continue

            # Port Name
            if normalized_line.startswith("name :") or normalized_line.startswith("name:"):
                parts = line.split(":", 1)
                if len(parts) == 2:
                    name = parts[1].strip()
                    interfaces[current_interface]["name"] = name
                    continue

            if ":" not in line:
                continue

            parts = line.split(":", 1)
            if len(parts) != 2:
                continue

            key = parts[0].strip().lower()
            value_str = parts[1].strip()

            def extract_numbers(text: str) -> list[int]:
                numbers: list[int] = []
                for match in re.finditer(r"(\d{1,3}(?:,\d{3})*)", text):
                    number_str = match.group(1).replace(",", "")
                    try:
                        numbers.append(int(number_str))
                    except ValueError:
                        continue
                return numbers

            def extract_float(text: str) -> float:
                """Extract floating point number from text."""
                match = re.search(r'(\d+(?:\.\d+)?)', text)
                if match:
                    try:
                        return float(match.group(1))
                    except ValueError:
                        pass
                return 0.0

            # Totals section
            if in_totals_section:
                if "bytes rx" in key:
                    numbers = extract_numbers(value_str)
                    if len(numbers) >= 2:
                        statistics[current_interface]["bytes_rx"] = numbers[0]
                        statistics[current_interface]["bytes_tx"] = numbers[1]
                    elif len(numbers) == 1:
                        statistics[current_interface]["bytes_rx"] = numbers[0]
                    continue

                if "unicast rx" in key and "pkts/sec" not in key:
                    numbers = extract_numbers(value_str)
                    if len(numbers) >= 2:
                        statistics[current_interface]["unicast_rx"] = numbers[0]
                        statistics[current_interface]["unicast_tx"] = numbers[1]
                        statistics[current_interface]["packets_in"] = numbers[0]
                        statistics[current_interface]["packets_out"] = numbers[1]
                    elif len(numbers) == 1:
                        statistics[current_interface]["unicast_rx"] = numbers[0]
                        statistics[current_interface]["packets_in"] = numbers[0]
                    continue

                if "bcast/mcast rx" in key or "b/mcast rx" in key:
                    numbers = extract_numbers(value_str)
                    if len(numbers) >= 2:
                        statistics[current_interface]["bcast_mcast_rx"] = numbers[0]
                        statistics[current_interface]["bcast_mcast_tx"] = numbers[1]
                    elif len(numbers) == 1:
                        statistics[current_interface]["bcast_mcast_rx"] = numbers[0]
                    continue

            # Errors section
            if in_errors_section:
                if "fcs rx" in key:
                    numbers = extract_numbers(value_str)
                    if len(numbers) >= 2:
                        statistics[current_interface]["fcs_rx"] = numbers[0]
                        statistics[current_interface]["drops_tx"] = numbers[1]
                    elif len(numbers) == 1:
                        statistics[current_interface]["fcs_rx"] = numbers[0]
                    continue

                if "alignment rx" in key:
                    numbers = extract_numbers(value_str)
                    if len(numbers) >= 2:
                        statistics[current_interface]["alignment_rx"] = numbers[0]
                        statistics[current_interface]["collisions_tx"] = numbers[1]
                    elif len(numbers) == 1:
                        statistics[current_interface]["alignment_rx"] = numbers[0]
                    continue

                if "runts rx" in key:
                    numbers = extract_numbers(value_str)
                    if len(numbers) >= 2:
                        statistics[current_interface]["runts_rx"] = numbers[0]
                        statistics[current_interface]["late_colln_tx"] = numbers[1]
                    elif len(numbers) == 1:
                        statistics[current_interface]["runts_rx"] = numbers[0]
                    continue

                if "giants rx" in key:
                    numbers = extract_numbers(value_str)
                    if len(numbers) >= 2:
                        statistics[current_interface]["giants_rx"] = numbers[0]
                        statistics[current_interface]["excessive_colln"] = numbers[1]
                    elif len(numbers) == 1:
                        statistics[current_interface]["giants_rx"] = numbers[0]
                    continue

                if "total rx errors" in key or "total errors" in key:
                    numbers = extract_numbers(value_str)
                    if len(numbers) >= 2:
                        statistics[current_interface]["total_rx_errors"] = numbers[0]
                        statistics[current_interface]["deferred_tx"] = numbers[1]
                    elif len(numbers) == 1:
                        statistics[current_interface]["total_rx_errors"] = numbers[0]
                    continue

            # Others section
            if in_others_section:
                if "discard rx" in key:
                    numbers = extract_numbers(value_str)
                    if len(numbers) >= 2:
                        statistics[current_interface]["discard_rx"] = numbers[0]
                        statistics[current_interface]["out_queue_len"] = numbers[1]
                    elif len(numbers) == 1:
                        statistics[current_interface]["discard_rx"] = numbers[0]
                    continue

                if "unknown protos" in key or "unknown proto" in key:
                    numbers = extract_numbers(value_str)
                    if len(numbers) >= 1:
                        statistics[current_interface]["unknown_protos"] = numbers[0]
                    continue

            # Rates section
            if in_rates_section:
                if "total rx (bps)" in key or "total rx" in key and "bps" in key:
                    numbers = extract_numbers(value_str)
                    if len(numbers) >= 2:
                        statistics[current_interface]["total_rx_bps"] = numbers[0]
                        statistics[current_interface]["total_tx_bps"] = numbers[1]
                    elif len(numbers) == 1:
                        statistics[current_interface]["total_rx_bps"] = numbers[0]
                    continue

                if "unicast rx (pkts/sec)" in key or ("unicast rx" in key and "pkts/sec" in key):
                    numbers = extract_numbers(value_str)
                    if len(numbers) >= 2:
                        statistics[current_interface]["unicast_rx_pps"] = numbers[0]
                        statistics[current_interface]["unicast_tx_pps"] = numbers[1]
                    elif len(numbers) == 1:
                        statistics[current_interface]["unicast_rx_pps"] = numbers[0]
                    continue

                if "b/mcast rx (pkts/sec)" in key or ("b/mcast rx" in key and "pkts/sec" in key):
                    numbers = extract_numbers(value_str)
                    if len(numbers) >= 2:
                        statistics[current_interface]["bcast_mcast_rx_pps"] = numbers[0]
                        statistics[current_interface]["bcast_mcast_tx_pps"] = numbers[1]
                    elif len(numbers) == 1:
                        statistics[current_interface]["bcast_mcast_rx_pps"] = numbers[0]
                    continue

                if "utilization rx" in key:
                    util_rx = extract_float(value_str)
                    statistics[current_interface]["utilization_rx_percent"] = util_rx
                    # Try to extract TX utilization from same line
                    if "utilization tx" in value_str.lower():
                        tx_match = re.search(r'utilization tx\s*:\s*([\d.]+)', value_str.lower())
                        if tx_match:
                            util_tx = float(tx_match.group(1))
                            statistics[current_interface]["utilization_tx_percent"] = util_tx
                    continue

                if "utilization tx" in key:
                    util_tx = extract_float(value_str)
                    statistics[current_interface]["utilization_tx_percent"] = util_tx
                    continue

        return interfaces, statistics, link_details
    
    def parse_show_interface_brief(self, output: str) -> Dict[str, Dict[str, Any]]:
        """Parse 'show interface brief' output for speed/duplex data.
        
        Args:
            output: Raw output from 'show interface brief' command
            
        Returns:
            Dictionary mapping port number to brief info (speed, duplex, etc.).
        """
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
                                elif mode == ".":
                                    # SFP ports show "." when no link - these are typically SFP/uplink ports
                                    # For ports 25-28 (common SFP ports), assume they are SFP capable
                                    try:
                                        port_int = int(port_num)
                                        if port_int >= 25:  # SFP ports are typically 25+
                                            speed_mbps = 1000  # SFP ports are typically 1Gbps capable
                                            duplex = "full"
                                    except ValueError:
                                        pass
                                
                                brief_info[port_num] = {
                                    "link_speed_mbps": speed_mbps,
                                    "duplex": duplex,
                                    "mode": mode,
                                    "mdi": right_fields[4] if len(right_fields) > 4 else "unknown",
                                    "port_type": right_fields[0] if len(right_fields) > 0 else "unknown",
                                    "intrusion_alert": right_fields[1].lower() == "yes" if len(right_fields) > 1 else False,
                                    "enabled": right_fields[2].lower() == "yes" if len(right_fields) > 2 else False,
                                    "flow_control": right_fields[5].lower() if len(right_fields) > 5 else "off",
                                }
                        except (ValueError, IndexError):
                            continue
        
        return brief_info
    
    def parse_show_power_over_ethernet_all(self, output: str) -> dict:
        """Parse 'show power-over-ethernet all' output for PoE status and detailed power information."""
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
                            poe_ports[current_port] = {
                                "power_enable": False,
                                "poe_status": "off",
                                "pse_voltage": 0.0,
                                "pd_amperage_draw": 0,
                                "pd_power_draw": 0.0,
                                "pse_reserved_power": 0.0,
                                "plc_class": "unknown",
                                "plc_type": "unknown",
                                "dlc_class": "unknown",
                                "dlc_type": "unknown",
                                "priority_config": "unknown",
                                "pre_std_detect": "unknown",
                                "lldp_pse_allocated": 0.0,
                                "lldp_pd_requested": 0.0,
                                "over_current_cnt": 0,
                                "power_denied_cnt": 0,
                                "short_cnt": 0,
                                "mps_absent_cnt": 0,
                            }
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
                            poe_ports[current_port] = {
                                "power_enable": False,
                                "poe_status": "off",
                                "pse_voltage": 0.0,
                                "pd_amperage_draw": 0,
                                "pd_power_draw": 0.0,
                                "pse_reserved_power": 0.0,
                                "plc_class": "unknown",
                                "plc_type": "unknown",
                                "dlc_class": "unknown",
                                "dlc_type": "unknown",
                                "priority_config": "unknown",
                                "pre_std_detect": "unknown",
                                "lldp_pse_allocated": 0.0,
                                "lldp_pd_requested": 0.0,
                                "over_current_cnt": 0,
                                "power_denied_cnt": 0,
                                "short_cnt": 0,
                                "mps_absent_cnt": 0,
                            }
                            port_found = True
                            break
                    except:
                        continue
            
            if port_found:
                continue
            elif current_port:
                # Parse PoE data for current port
                def parse_combined_line(line_text):
                    parsed_fields = {}
                    import re
                    matches = re.findall(r'([^:]+?)\s*:\s*([^:]*?)(?=\s{3,}[^:]+\s*:|$)', line_text)
                    for key, value in matches:
                        key = key.strip().lower()
                        value = value.strip()
                        parsed_fields[key] = value
                    return parsed_fields
                
                parsed_data = parse_combined_line(line)
                
                for key, value in parsed_data.items():
                    value_lower = value.lower()
                    
                    if "power enable" in key:
                        is_enabled = "yes" in value_lower
                        poe_ports[current_port]["power_enable"] = is_enabled
                    
                    elif "poe port status" in key or "poe status" in key:
                        poe_status_str = "off"
                        if "searching" in value_lower:
                            poe_status_str = "searching"
                        elif "delivering" in value_lower or "deliver" in value_lower:
                            poe_status_str = "delivering"
                        elif "enabled" in value_lower or "on" in value_lower or "active" in value_lower:
                            poe_status_str = "on"
                        elif "fault" in value_lower or "error" in value_lower or "overload" in value_lower:
                            poe_status_str = "fault"
                        elif "denied" in value_lower or "reject" in value_lower:
                            poe_status_str = "denied"
                        poe_ports[current_port]["poe_status"] = poe_status_str
                    
                    # Parse power and electrical values
                    elif "pse voltage" in key:
                        import re
                        match = re.search(r'([\d.]+)', value)
                        if match:
                            poe_ports[current_port]["pse_voltage"] = float(match.group(1))
                    
                    elif "pd amperage draw" in key:
                        import re
                        match = re.search(r'(\d+)', value)
                        if match:
                            poe_ports[current_port]["pd_amperage_draw"] = int(match.group(1))
                    
                    elif "pd power draw" in key:
                        import re
                        match = re.search(r'([\d.]+)', value)
                        if match:
                            poe_ports[current_port]["pd_power_draw"] = float(match.group(1))
                    
                    elif "pse reserved power" in key:
                        import re
                        match = re.search(r'([\d.]+)', value)
                        if match:
                            poe_ports[current_port]["pse_reserved_power"] = float(match.group(1))
                    
                    # Parse PoE class and type
                    elif "plc class" in key:
                        poe_ports[current_port]["plc_class"] = value
                    
                    elif "plc type" in key:
                        poe_ports[current_port]["plc_type"] = value
                    
                    elif "dlc class" in key:
                        poe_ports[current_port]["dlc_class"] = value
                    
                    elif "dlc type" in key:
                        poe_ports[current_port]["dlc_type"] = value
                    
                    # Parse priority and detection
                    elif "priority config" in key:
                        poe_ports[current_port]["priority_config"] = value_lower
                    
                    elif "pre-std detect" in key:
                        poe_ports[current_port]["pre_std_detect"] = value_lower
                    
                    # Parse LLDP power information
                    elif "lldp pse allocated" in key:
                        import re
                        match = re.search(r'([\d.]+)', value)
                        if match:
                            poe_ports[current_port]["lldp_pse_allocated"] = float(match.group(1))
                    
                    elif "lldp pd requested" in key:
                        import re
                        match = re.search(r'([\d.]+)', value)
                        if match:
                            poe_ports[current_port]["lldp_pd_requested"] = float(match.group(1))
                    
                    # Parse error/fault counters
                    elif "over current cnt" in key:
                        import re
                        match = re.search(r'(\d+)', value)
                        if match:
                            poe_ports[current_port]["over_current_cnt"] = int(match.group(1))
                    
                    elif "power denied cnt" in key:
                        import re
                        match = re.search(r'(\d+)', value)
                        if match:
                            poe_ports[current_port]["power_denied_cnt"] = int(match.group(1))
                    
                    elif "short cnt" in key:
                        import re
                        match = re.search(r'(\d+)', value)
                        if match:
                            poe_ports[current_port]["short_cnt"] = int(match.group(1))
                    
                    elif "mps absent cnt" in key:
                        import re
                        match = re.search(r'(\d+)', value)
                        if match:
                            poe_ports[current_port]["mps_absent_cnt"] = int(match.group(1))
        
        return poe_ports

    def parse_show_version(self, output: str) -> dict:
        """Parse 'show version' output for firmware and version information."""
        version_info = {}
        main_firmware_version = None
        boot_version = None
        
        _LOGGER.debug(f"🔍 VERSION PARSING: Processing {len(output)} characters of version output")
        
        for line in output.split('\n'):
            line = line.strip()
            if not line:
                continue
                
            line_lower = line.lower()
            
            # Extract switch model from command prompt (e.g., "HP-2530-24G-PoEP#")
            # Look for HP model patterns in any line, not just those ending with #
            if ('hp-' in line_lower or 'aruba-' in line_lower) and ('#' in line or 'show' in line_lower):
                import re
                # More flexible pattern to catch model names in various contexts
                model_match = re.search(r'((?:HP|Aruba)-[A-Z0-9-]+)', line, re.IGNORECASE)
                if model_match:
                    version_info["model"] = model_match.group(1)
                    _LOGGER.debug(f"🏷️ VERSION PARSING: Found model in line: {model_match.group(1)} from line: {line}")
            elif line.endswith('#') and '-' in line and 'hp' in line_lower:
                # Fallback: original logic for lines ending with #
                import re
                model_match = re.search(r'(HP-[A-Z0-9-]+)', line, re.IGNORECASE)
                if model_match:
                    version_info["model"] = model_match.group(1)
                    _LOGGER.debug(f"🏷️ VERSION PARSING: Found model in prompt: {model_match.group(1)} from line: {line}")
            
            # Parse various version fields from HP/Aruba switches
            if ":" in line:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    key = parts[0].strip().lower()
                    value = parts[1].strip()
                    
                    # Map common version fields
                    if any(x in key for x in ["software revision", "firmware revision", "version", "release"]):
                        version_info["firmware_version"] = value
                    elif any(x in key for x in ["rom version", "boot rom", "bootrom"]):
                        boot_version = value  # Store but don't use as primary
                        _LOGGER.debug(f"🔧 VERSION PARSING: Found boot ROM version: {value} from key: {key}")
                    elif any(x in key for x in ["model", "product", "type"]):
                        if "model" not in version_info:  # Don't override hostname-extracted model
                            version_info["model"] = value
                    elif any(x in key for x in ["serial", "serial number"]):
                        version_info["serial_number"] = value
                    elif any(x in key for x in ["mac address", "base mac"]):
                        version_info["mac_address"] = value
                    elif any(x in key for x in ["hardware", "hw rev"]):
                        version_info["hardware_revision"] = value
                    elif any(x in key for x in ["uptime", "system uptime"]):
                        version_info["uptime"] = value
                        
            # Also look for version patterns in any line - not just those with version keywords
            # Handle version lines that don't follow key:value format
            if "ya." in line_lower or "kb." in line_lower or "yc." in line_lower:
                # Aruba version format like "YA.16.08.0002"
                import re
                version_match = re.search(r'[YK][A-Z]\.[\.\d]+', line, re.IGNORECASE)
                if version_match:
                    version_str = version_match.group()
                    _LOGGER.debug(f"📟 VERSION PARSING: Found version string: {version_str} from line: {line}")
                    # If this looks like a main firmware version (longer), prefer it
                    if len(version_str) > 8:  # YA.16.08.0002 is longer than YA.15.20
                        main_firmware_version = version_str
                        _LOGGER.debug(f"🎯 VERSION PARSING: Set as main firmware (length {len(version_str)}): {version_str}")
                    elif main_firmware_version is None:
                        main_firmware_version = version_str
                        _LOGGER.debug(f"🔄 VERSION PARSING: Set as fallback firmware: {version_str}")
        
        # Use main firmware version if found, otherwise use boot version, otherwise "Unknown"
        if main_firmware_version:
            version_info["firmware_version"] = main_firmware_version
            _LOGGER.debug(f"✅ VERSION PARSING: Using main firmware version: {main_firmware_version}")
        elif "firmware_version" not in version_info and boot_version:
            version_info["firmware_version"] = boot_version
            _LOGGER.debug(f"⚠️ VERSION PARSING: Fallback to boot ROM version: {boot_version}")
        elif "firmware_version" not in version_info:
            version_info["firmware_version"] = "Unknown"
            _LOGGER.debug(f"❌ VERSION PARSING: No version found, using Unknown")
            
        # Set defaults for missing fields
        if "model" not in version_info:
            version_info["model"] = "HP/Aruba Switch"
            _LOGGER.debug(f"⚠️ VERSION PARSING: No model found, using default: HP/Aruba Switch")
        if "serial_number" not in version_info:
            version_info["serial_number"] = "Unknown"
            
        _LOGGER.debug(f"🏁 VERSION PARSING FINAL: {version_info}")
        return version_info

    async def get_current_data(self) -> dict:
        """Get current data from switch - no caching, just live data."""
        try:
            _LOGGER.debug(f"🔄 Getting live data for {self.host}")
            # Execute all commands in a single session
            interfaces, statistics, link_details, poe_ports, version_info = await self.get_all_switch_data()
            _LOGGER.debug(f"✅ get_all_switch_data completed for {self.host}")
            
            if interfaces or statistics or link_details or poe_ports or version_info:
                # Mark as available and update successful connection time
                was_offline = not self._is_available
                self._is_available = True
                self._last_successful_connection = time.time()
                if was_offline:
                    _LOGGER.info(f"Switch {self.host} is back online")
                
                # Return structured data for coordinator
                return {
                    "interfaces": interfaces,
                    "statistics": statistics,
                    "link_details": link_details,
                    "poe_ports": poe_ports,
                    "version_info": version_info,
                    "available": True,
                    "last_successful_connection": self._last_successful_connection,
                }
            else:
                _LOGGER.warning(f"❌ No data received from {self.host}")
                self._is_available = False
                return {"available": False}
                
        except Exception as e:
            _LOGGER.error(f"❌ Failed to get data from {self.host}: {e}")
            # Update availability status
            was_online = self._is_available
            self._is_available = False
            if was_online:
                _LOGGER.warning(f"Switch {self.host} went offline (data error: {e})")
            return {"available": False}

    async def is_switch_available(self) -> bool:
        """Check if the switch is currently available (connected)."""
        return self._is_available
    
    async def test_connectivity(self) -> bool:
        """Test switch connectivity by executing a simple command. Updates availability status."""
        try:
            result = await self.execute_command("show version", timeout=5)
            success = result is not None and len(result.strip()) > 0
            
            self._is_available = success
            if success:
                self._last_successful_connection = time.time()
            
            _LOGGER.info(f"Connectivity test for {self.host}: {'SUCCESS' if success else 'FAILED'}")
            return success
        except Exception as e:
            _LOGGER.warning(f"Connectivity test failed for {self.host}: {e}")
            self._is_available = False
            return False

# Global connection managers
_connection_managers: Dict[str, ArubaSSHManager] = {}

def get_ssh_manager(host: str, username: str, password: str, ssh_port: int = 22) -> ArubaSSHManager:
    """Get or create an SSH manager for the given host."""
    key = f"{host}:{ssh_port}"
    if key not in _connection_managers:
        _connection_managers[key] = ArubaSSHManager(host, username, password, ssh_port)
    return _connection_managers[key]