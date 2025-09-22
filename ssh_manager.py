"""SSH connection manager for Aruba Switch integration."""
import logging
import asyncio
import paramiko
from typing import Optional, Dict, Any
import time

_LOGGER = logging.getLogger(__name__)

class ArubaSSHManager:
    """Manages SSH connections to Aruba switches with connection pooling and retry logic."""
    
    def __init__(self, host: str, username: str, password: str, ssh_port: int = 22):
        self.host = host
        self.username = username
        self.password = password
        self.ssh_port = ssh_port
        self._connection_lock = asyncio.Lock()
        self._last_connection_attempt = 0
        self._connection_backoff = 1  # seconds
        self._max_backoff = 30
        
    async def execute_command(self, command: str, timeout: int = 15) -> Optional[str]:
        """Execute a command on the switch with proper connection management."""
        async with self._connection_lock:
            # Implement backoff to avoid overwhelming the switch
            time_since_last = time.time() - self._last_connection_attempt
            if time_since_last < self._connection_backoff:
                await asyncio.sleep(self._connection_backoff - time_since_last)
            
            self._last_connection_attempt = time.time()
            
            def _sync_execute():
                ssh = None
                try:
                    ssh = paramiko.SSHClient()
                    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                    
                    # Connection parameters optimized for Aruba switches
                    connect_params = {
                        'hostname': self.host,
                        'username': self.username,
                        'password': self.password,
                        'port': self.ssh_port,
                        'timeout': timeout,
                        'auth_timeout': 10,
                        'banner_timeout': 15,  # Increased banner timeout
                        'look_for_keys': False,
                        'allow_agent': False,
                    }
                    
                    # Try different SSH configurations for maximum compatibility
                    ssh_configs = [
                        # Modern SSH
                        {},
                        # Force older algorithms for legacy switches
                        {
                            'disabled_algorithms': {
                                'kex': ['diffie-hellman-group14-sha256', 'diffie-hellman-group16-sha512'],
                                'ciphers': ['aes128-ctr', 'aes192-ctr', 'aes256-ctr'],
                                'macs': []
                            }
                        },
                        # Very legacy compatibility
                        {
                            'disabled_algorithms': {
                                'kex': ['diffie-hellman-group14-sha256', 'diffie-hellman-group16-sha512', 
                                       'ecdh-sha2-nistp256', 'ecdh-sha2-nistp384', 'ecdh-sha2-nistp521'],
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
                            
                            # Execute command
                            stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
                            output = stdout.read().decode('utf-8', errors='ignore')
                            error_output = stderr.read().decode('utf-8', errors='ignore')
                            exit_status = stdout.channel.recv_exit_status()
                            
                            if exit_status != 0 and error_output:
                                _LOGGER.warning(f"Command '{command}' returned non-zero exit status on {self.host}: {error_output}")
                            
                            # Reset backoff on successful connection
                            self._connection_backoff = 1
                            return output
                            
                        except (paramiko.SSHException, EOFError, OSError) as e:
                            if i == len(ssh_configs) - 1:  # Last attempt
                                # Increase backoff for next time
                                self._connection_backoff = min(self._connection_backoff * 2, self._max_backoff)
                                raise e
                            continue
                    
                    return None
                    
                except paramiko.AuthenticationException as e:
                    _LOGGER.error(f"Authentication failed for {self.host}: {e}")
                    raise
                except Exception as e:
                    _LOGGER.error(f"SSH error connecting to {self.host}: {e}")
                    # Increase backoff
                    self._connection_backoff = min(self._connection_backoff * 2, self._max_backoff)
                    raise
                finally:
                    if ssh:
                        try:
                            ssh.close()
                        except:
                            pass
            
            # Run in executor
            loop = asyncio.get_event_loop()
            try:
                result = await loop.run_in_executor(None, _sync_execute)
                return result
            except Exception as e:
                _LOGGER.debug(f"SSH command '{command}' failed for {self.host}: {e}")
                return None

# Global connection managers
_connection_managers: Dict[str, ArubaSSHManager] = {}

def get_ssh_manager(host: str, username: str, password: str, ssh_port: int = 22) -> ArubaSSHManager:
    """Get or create an SSH manager for the given host."""
    key = f"{host}:{ssh_port}"
    if key not in _connection_managers:
        _connection_managers[key] = ArubaSSHManager(host, username, password, ssh_port)
    return _connection_managers[key]