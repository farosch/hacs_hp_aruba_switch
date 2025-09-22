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
        
    async def execute_command(self, command: str, timeout: int = 10) -> Optional[str]:
        """Execute a command on the switch with proper connection management."""
        # Use global semaphore to limit concurrent connections
        async with _CONNECTION_SEMAPHORE:
            # Much shorter timeout to prevent blocking
            async with asyncio.wait_for(self._connection_lock.acquire(), timeout=2):
                try:
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
                                    
                                    # Execute command with shorter timeout
                                    stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
                                    output = stdout.read().decode('utf-8', errors='ignore')
                                    error_output = stderr.read().decode('utf-8', errors='ignore')
                                    exit_status = stdout.channel.recv_exit_status()
                                    
                                    if exit_status != 0 and error_output:
                                        _LOGGER.debug(f"Command '{command}' returned non-zero exit status on {self.host}: {error_output}")
                                    
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
                finally:
                    self._connection_lock.release()

# Global connection managers
_connection_managers: Dict[str, ArubaSSHManager] = {}

def get_ssh_manager(host: str, username: str, password: str, ssh_port: int = 22) -> ArubaSSHManager:
    """Get or create an SSH manager for the given host."""
    key = f"{host}:{ssh_port}"
    if key not in _connection_managers:
        _connection_managers[key] = ArubaSSHManager(host, username, password, ssh_port)
    return _connection_managers[key]