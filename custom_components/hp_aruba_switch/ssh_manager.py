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
                            except:
                                pass
                
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


    async def get_all_switch_data(self) -> tuple[dict, dict, dict, dict, dict]:
        """Execute all commands in a single SSH session and parse the combined output."""
        # Define all commands we need to execute
        commands = [
            "show interface all",
            "show interface brief", 
            "show power-over-ethernet all",
            "show version"
        ]
        
        # Combine all commands into a single multi-line command
        combined_command = "\n".join(commands)
        
        _LOGGER.debug(f"🔗 Executing combined commands in single session: {commands}")
        result = await self.execute_command(combined_command, timeout=30)
        
        if not result:
            _LOGGER.warning(f"❌ Combined command execution failed for {self.host}")
            return {}, {}, {}, {}, {}
        
        _LOGGER.info(f"✅ Successfully executed {len(commands)} commands in single session for {self.host}")
        _LOGGER.debug(f"📊 Combined output length: {len(result)} characters")
        
        # Parse the combined output with timeout
        _LOGGER.debug(f"🔍 Starting to parse combined output for {self.host}")
        try:
            # Run parsing in executor with timeout to prevent hanging
            loop = asyncio.get_event_loop()
            parsed_result = await asyncio.wait_for(
                loop.run_in_executor(None, self._parse_combined_output, result, commands),
                timeout=15.0  # 15 second timeout for parsing
            )
            _LOGGER.debug(f"✅ Parsing completed for {self.host}")
            return parsed_result
        except asyncio.TimeoutError:
            _LOGGER.error(f"❌ Parsing timed out after 15s for {self.host}")
            return {}, {}, {}, {}, {}
        except Exception as e:
            _LOGGER.error(f"❌ Parsing failed for {self.host}: {e}")
            return {}, {}, {}, {}, {}
    
    def _parse_combined_output(self, output: str, commands: list) -> tuple[dict, dict, dict, dict, dict]:
        """Parse the combined output from all commands."""
        _LOGGER.error(f"🚨 PARSING STARTED! Output length: {len(output)} for {self.host}")
        _LOGGER.debug(f"🔍 _parse_combined_output starting, output length: {len(output)}")
        interfaces = {}
        statistics = {}
        link_details = {}
        poe_ports = {}
        version_info = {}
        _LOGGER.error(f"🚨 PARSING CHECKPOINT 1: Dictionaries initialized for {self.host}")
        
        # Split output by command boundaries - look for command echoes or patterns
        _LOGGER.debug(f"🔪 Starting output splitting")
        _LOGGER.error(f"🚨 PARSING CHECKPOINT 2: About to call _split_output_by_commands for {self.host}")
        sections = self._split_output_by_commands(output, commands)
        _LOGGER.error(f"🚨 PARSING CHECKPOINT 3: _split_output_by_commands completed, got {len(sections)} sections for {self.host}")
        _LOGGER.debug(f"✂️ Output splitting completed, got {len(sections)} sections")
        
        for i, (cmd, section_output) in enumerate(sections.items()):
            _LOGGER.debug(f"🔄 Processing section {i+1}/{len(sections)} for command '{cmd}' (length: {len(section_output)})")
            
            if "show interface all" in cmd:
                # Parse interface status and statistics
                _LOGGER.debug(f"📊 Starting interface all parsing")
                ifaces, stats, links = self._parse_interface_all_output(section_output)
                _LOGGER.debug(f"📈 Interface all completed: {len(ifaces)} interfaces, {len(stats)} stats, {len(links)} links")
                interfaces.update(ifaces)
                statistics.update(stats)
                link_details.update(links)
                
            elif "show interface brief" in cmd:
                # Parse brief interface info
                _LOGGER.debug(f"📋 Starting interface brief parsing")
                brief_info = self._parse_interface_brief_output(section_output)
                _LOGGER.debug(f"📑 Interface brief completed: {len(brief_info)} interfaces")
                # Merge brief info into link_details (only speed/duplex info)
                for port, info in brief_info.items():
                    if port in link_details:
                        # Update existing link details with brief info (speed/duplex only)
                        link_details[port].update({
                            "link_speed": f"{info['link_speed_mbps']} Mbps" if info['link_speed_mbps'] > 0 else "unknown",
                            "duplex": info["duplex"],
                            "mode": info.get("mode", "unknown"),
                            "mdi": info.get("mdi", "unknown")
                        })
                    else:
                        # Create new link details entry with speed/duplex from brief, defaults for others
                        link_details[port] = {
                            "link_up": False,  # Default, will be set by detailed parsing if available
                            "port_enabled": False,  # Default, will be set by detailed parsing if available
                            "link_speed": f"{info['link_speed_mbps']} Mbps" if info['link_speed_mbps'] > 0 else "unknown",
                            "duplex": info["duplex"],
                            "auto_negotiation": "unknown",
                            "cable_type": "unknown",
                            "mode": info.get("mode", "unknown"),
                            "mdi": info.get("mdi", "unknown")
                        }
                        
            elif "show power-over-ethernet all" in cmd:
                # Parse PoE status
                _LOGGER.debug(f"⚡ Starting PoE parsing")
                poe_data = self._parse_poe_output(section_output)
                _LOGGER.debug(f"🔌 PoE completed: {len(poe_data)} ports")
                poe_ports.update(poe_data)
                
            elif "show version" in cmd:
                # Parse version and firmware information
                _LOGGER.debug(f"📟 Starting version parsing")
                _LOGGER.debug(f"🔍 RAW VERSION OUTPUT: {repr(section_output)}")
                version_data = self._parse_version_output(section_output)
                _LOGGER.debug(f"📝 Version completed: {bool(version_data)}")
                version_info.update(version_data)
        
        _LOGGER.debug(f"Parsed from combined output: {len(interfaces)} interfaces, {len(statistics)} statistics, "
                     f"{len(link_details)} link details, {len(poe_ports)} PoE ports, version info: {bool(version_info)}")
        
        return interfaces, statistics, link_details, poe_ports, version_info
    
    def _split_output_by_commands(self, output: str, commands: list) -> dict:
        """Split the combined output into sections for each command."""
        _LOGGER.error(f"🚨 SPLIT_OUTPUT_BY_COMMANDS STARTED for {self.host} with {len(commands)} commands")
        sections = {}
        current_section = ""
        current_command = None
        
        lines = output.split('\n')
        _LOGGER.error(f"🚨 SPLIT_OUTPUT: Split into {len(lines)} lines for {self.host}")
        
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
            # CRITICAL: Don't match "Port Enabled" lines as interface headers!
            if ("port counters for port" in line.lower() or 
                "interface" in line.lower() and any(x in line.lower() for x in ["port", "ethernet", "gi", "fa", "te"]) or
                (line.lower().startswith("port") and "port counters" in line.lower()) or
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
                            "duplex": "unknown"
                        }
                        _LOGGER.debug(f"Started parsing port {current_interface} from line: '{line}'")
                except Exception as e:
                    continue
                    
            elif current_interface:
                line_lower = line.lower()
                
                # Parse port status, link details, and statistics using existing logic
                # Bulletproof parsing: use simple string matching with whitespace normalization
                import re
                
                # Debug: Log every line that contains "enabled" to see what we're working with
                if "enabled" in line_lower:
                    _LOGGER.debug(f"Port {current_interface}: DEBUG - Line contains 'enabled': '{line}' (repr: {repr(line)})")
                
                # Normalize whitespace and check for "port enabled" followed by colon pattern
                normalized_line = re.sub(r'\s+', ' ', line_lower.strip())
                if ('port enabled :' in normalized_line) or ('port enabled:' in normalized_line):
                    value_part = line.split(":", 1)[1].strip().lower()
                    is_enabled = any(pos in value_part for pos in ["yes", "enabled", "up", "active", "true"])
                    interfaces[current_interface]["port_enabled"] = is_enabled
                    link_details[current_interface]["port_enabled"] = is_enabled
                    _LOGGER.debug(f"Port {current_interface}: Found 'Port Enabled' line: '{line}' -> value_part: '{value_part}' -> is_enabled: {is_enabled}")
                
                # Bulletproof parsing: use simple string matching with whitespace normalization for Link Status  
                elif ('link status :' in normalized_line) or ('link status:' in normalized_line):
                    value_part = line.split(":", 1)[1].strip().lower()
                    link_up = "up" in value_part
                    interfaces[current_interface]["link_status"] = "up" if link_up else "down"
                    link_details[current_interface]["link_up"] = link_up
                    _LOGGER.debug(f"Port {current_interface}: Found 'Link Status' line: '{line}' -> value_part: '{value_part}' -> link_up: {link_up}")
                
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
                        
                        # Handle HP/Aruba switch format: "Bytes Rx        : 171,771,942          Bytes Tx        : 142,120,852"
                        if "bytes rx" in key:
                            # Extract all numbers from the line (includes both Rx and Tx values)  
                            numbers = extract_numbers(value_str)
                            if len(numbers) >= 2:
                                statistics[current_interface]["bytes_rx"] = numbers[0]
                                statistics[current_interface]["bytes_tx"] = numbers[1]
                            elif len(numbers) == 1:
                                statistics[current_interface]["bytes_rx"] = numbers[0]
                        # Handle HP/Aruba switch format: "Unicast Rx      : 239,357              Unicast Tx      : 195,819"
                        elif "unicast rx" in key:
                            # Extract all numbers from the line (includes both Rx and Tx values)
                            numbers = extract_numbers(value_str)
                            if len(numbers) >= 2:
                                statistics[current_interface]["unicast_rx"] = numbers[0]
                                statistics[current_interface]["unicast_tx"] = numbers[1]
                            elif len(numbers) == 1:
                                statistics[current_interface]["unicast_rx"] = numbers[0]
        
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

    def _parse_version_output(self, output: str) -> dict:
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
                    "available": True
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