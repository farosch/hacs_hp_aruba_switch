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
        result = await self.execute_command("show interface all", timeout=15)
        if not result:
            return {}, {}, {}
        
        interfaces = {}
        statistics = {}
        link_details = {}
        current_interface = None
        
        for line in result.split('\n'):
            line = line.strip()
            if not line:
                continue
                
            # Look for interface headers like "Status and Counters - Port Counters for port X"
            if "port counters for port" in line.lower():
                try:
                    port_num = line.split("port")[-1].strip()
                    current_interface = port_num
                    interfaces[current_interface] = {"port_enabled": False, "link_status": "down"}
                    statistics[current_interface] = {"bytes_in": 0, "bytes_out": 0, "packets_in": 0, "packets_out": 0}
                    link_details[current_interface] = {
                        "link_up": False, "port_enabled": False, "link_speed": "unknown",
                        "duplex": "unknown", "auto_negotiation": "unknown", "cable_type": "unknown"
                    }
                except:
                    continue
            elif current_interface:
                line_lower = line.lower()
                _LOGGER.debug(f"Parsing interface line for port {current_interface}: {repr(line)}")
                
                # Check for port enabled/disabled status - handle multiple formats
                if any(keyword in line_lower for keyword in ["port enabled", "enabled", "status"]):
                    # Look for enabled/disabled or yes/no indicators
                    if ":" in line:
                        value_part = line.split(":", 1)[1].strip().lower()
                        is_enabled = any(pos in value_part for pos in ["yes", "enabled", "up", "active"])
                        interfaces[current_interface]["port_enabled"] = is_enabled
                        link_details[current_interface]["port_enabled"] = is_enabled
                        _LOGGER.debug(f"Found port status for {current_interface}: {is_enabled} (from '{value_part}')")
                
                # Check for link status
                elif "link status" in line_lower:
                    if ":" in line:
                        value_part = line.split(":", 1)[1].strip().lower()
                        link_up = "up" in value_part
                        interfaces[current_interface]["link_status"] = "up" if link_up else "down"
                        link_details[current_interface]["link_up"] = link_up
                        _LOGGER.debug(f"Found link status for {current_interface}: {'up' if link_up else 'down'}")
                
                # Parse additional link details
                elif "speed" in line_lower and (":" in line or "mbps" in line_lower or "gbps" in line_lower):
                    # Extract speed value
                    import re
                    speed_match = re.search(r'(\d+)\s*(mbps|gbps|mb|gb)', line_lower)
                    if speed_match:
                        speed_val = speed_match.group(1)
                        speed_unit = speed_match.group(2)
                        if "gb" in speed_unit:
                            link_details[current_interface]["link_speed"] = f"{speed_val} Gbps"
                        else:
                            link_details[current_interface]["link_speed"] = f"{speed_val} Mbps"
                
                elif "duplex" in line_lower:
                    if "full" in line_lower:
                        link_details[current_interface]["duplex"] = "full"
                    elif "half" in line_lower:
                        link_details[current_interface]["duplex"] = "half"
                
                elif ("auto" in line_lower and "neg" in line_lower) or "autoneg" in line_lower:
                    if ":" in line:
                        value_part = line.split(":", 1)[1].strip().lower()
                        auto_enabled = any(pos in value_part for pos in ["yes", "enabled", "on", "active"])
                        link_details[current_interface]["auto_negotiation"] = "enabled" if auto_enabled else "disabled"
                
                # Parse statistics from the same output
                elif any(keyword in line_lower for keyword in ["bytes received", "input bytes", "rx bytes"]):
                    numbers = [int(s) for s in line.split() if s.isdigit()]
                    if numbers:
                        statistics[current_interface]["bytes_in"] = numbers[0]
                        _LOGGER.debug(f"Found bytes_in for {current_interface}: {numbers[0]}")
                
                elif any(keyword in line_lower for keyword in ["bytes transmitted", "output bytes", "tx bytes"]):
                    numbers = [int(s) for s in line.split() if s.isdigit()]
                    if numbers:
                        statistics[current_interface]["bytes_out"] = numbers[0]
                        _LOGGER.debug(f"Found bytes_out for {current_interface}: {numbers[0]}")
                
                elif any(keyword in line_lower for keyword in ["packets received", "input packets", "rx packets"]):
                    numbers = [int(s) for s in line.split() if s.isdigit()]
                    if numbers:
                        statistics[current_interface]["packets_in"] = numbers[0]
                        _LOGGER.debug(f"Found packets_in for {current_interface}: {numbers[0]}")
                
                elif any(keyword in line_lower for keyword in ["packets transmitted", "output packets", "tx packets"]):
                    numbers = [int(s) for s in line.split() if s.isdigit()]
                    if numbers:
                        statistics[current_interface]["packets_out"] = numbers[0]
                        _LOGGER.debug(f"Found packets_out for {current_interface}: {numbers[0]}")
                
                # Alternative format: look for colon-separated values for statistics
                elif ":" in line:
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        key = parts[0].strip().lower()
                        value_str = parts[1].strip()
                        
                        # Extract first number from value
                        numbers = [int(s) for s in value_str.split() if s.isdigit()]
                        if numbers:
                            value = numbers[0]
                            
                            if "bytes" in key and ("in" in key or "received" in key or "rx" in key):
                                statistics[current_interface]["bytes_in"] = value
                            elif "bytes" in key and ("out" in key or "transmitted" in key or "tx" in key):
                                statistics[current_interface]["bytes_out"] = value
                            elif "packets" in key and ("in" in key or "received" in key or "rx" in key):
                                statistics[current_interface]["packets_in"] = value
                            elif "packets" in key and ("out" in key or "transmitted" in key or "tx" in key):
                                statistics[current_interface]["packets_out"] = value
        
        _LOGGER.debug(f"Parsed {len(interfaces)} interfaces, {len(statistics)} statistics, and {len(link_details)} link details from bulk query")
        return interfaces, statistics, link_details

    async def get_all_poe_status(self) -> dict:
        """Get PoE status for all ports in a single query."""
        result = await self.execute_command("show power-over-ethernet all", timeout=15)
        if not result:
            return {}
        
        poe_ports = {}
        current_port = None
        
        for line in result.split('\n'):
            line = line.strip()
            if not line:
                continue
                
            # Look for port headers like "Status and Configuration Information for port X"
            if "information for port" in line.lower():
                try:
                    port_num = line.split("port")[-1].strip()
                    current_port = port_num
                    poe_ports[current_port] = {"power_enable": False, "poe_status": "off"}
                except:
                    continue
            elif current_port:
                line_lower = line.lower()
                _LOGGER.debug(f"Parsing PoE line for port {current_port}: {repr(line)}")
                
                if "power enable" in line_lower:
                    if ":" in line:
                        value_part = line.split(":", 1)[1].strip().lower()
                        is_enabled = "yes" in value_part
                        poe_ports[current_port]["power_enable"] = is_enabled
                        _LOGGER.debug(f"Found PoE power enable for {current_port}: {is_enabled}")
                        
                elif "poe port status" in line_lower or "poe status" in line_lower:
                    if ":" in line:
                        value_part = line.split(":", 1)[1].strip().lower()
                        # PoE is considered "on" if it's delivering, searching, or enabled
                        poe_active = any(status in value_part for status in 
                            ["delivering", "searching", "enabled", "on", "active"])
                        poe_ports[current_port]["poe_status"] = poe_active
                        _LOGGER.debug(f"Found PoE status for {current_port}: {poe_active} (from '{value_part}')")
        
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
            return self._statistics_cache.get(port, {
                "bytes_in": 0,
                "bytes_out": 0,
                "packets_in": 0,
                "packets_out": 0
            })

    async def get_port_link_status(self, port: str) -> dict:
        """Get cached detailed link status information for a specific port."""
        await self.update_bulk_cache()
        
        async with self._cache_lock:
            return self._link_cache.get(port, {
                "link_up": False,
                "port_enabled": False,
                "link_speed": "unknown",
                "duplex": "unknown", 
                "auto_negotiation": "unknown",
                "cable_type": "unknown"
            })

# Global connection managers
_connection_managers: Dict[str, ArubaSSHManager] = {}

def get_ssh_manager(host: str, username: str, password: str, ssh_port: int = 22) -> ArubaSSHManager:
    """Get or create an SSH manager for the given host."""
    key = f"{host}:{ssh_port}"
    if key not in _connection_managers:
        _connection_managers[key] = ArubaSSHManager(host, username, password, ssh_port)
    return _connection_managers[key]