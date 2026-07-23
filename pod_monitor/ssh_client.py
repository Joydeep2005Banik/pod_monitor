import asyncio
import asyncssh
import re
from typing import List, Optional, Callable, Any
from datetime import datetime
import logging

from .models import LogEntry, LogLevel, PodMetrics

logger = logging.getLogger(__name__)

class SSHClient:
    def __init__(self, host: str, username: str, password: Optional[str] = None, 
                 key_path: Optional[str] = None, port: int = 22):
        self.host = host
        self.username = username
        self.password = password
        self.key_path = key_path
        self.port = port
        self.connection: Optional[asyncssh.SSHClientConnection] = None

    async def connect(self) -> bool:
        """Establish SSH connection to the pod."""
        try:
            if self.key_path:
                self.connection = await asyncssh.connect(
                    self.host,
                    username=self.username,
                    client_keys=[self.key_path],
                    port=self.port,
                    known_hosts=None  # For production, use proper known_hosts
                )
            elif self.password:
                self.connection = await asyncssh.connect(
                    self.host,
                    username=self.username,
                    password=self.password,
                    port=self.port,
                    known_hosts=None
                )
            else:
                raise ValueError("Either password or key_path must be provided")
            
            logger.info(f"Connected to {self.host}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to {self.host}: {e}")
            return False

    async def execute_command(self, command: str) -> str:
        """Execute a command on the remote pod."""
        if not self.connection:
            raise ConnectionError("Not connected to pod")
        
        result = await self.connection.run(command, check=True)
        return result.stdout

    async def get_pod_logs(self, pod_name: str, tail: int = 100, 
                          namespace: str = "default") -> List[LogEntry]:
        """Fetch logs from a specific pod using kubectl."""
        cmd = f"kubectl logs {pod_name} -n {namespace} --tail={tail}"
        
        try:
            output = await self.execute_command(cmd)
            return self.parse_logs(output, pod_name)
        except Exception as e:
            logger.error(f"Error fetching logs from {self.host}: {e}")
            return []

    async def get_pod_metrics(self, pod_name: str, namespace: str = "default") -> PodMetrics:
        """Get CPU and memory metrics for a pod."""
        metrics = PodMetrics()
        
        try:
            # Get pod metrics
            cmd = f"kubectl top pod {pod_name} -n {namespace} --no-headers"
            output = await self.execute_command(cmd)
            
            # Parse output: "pod-name   100m   500Mi"
            parts = output.strip().split()
            if len(parts) >= 3:
                cpu_str = parts[1].replace('m', '')
                mem_str = parts[2].replace('Mi', '').replace('Gi', '')
                
                metrics.cpu_usage = float(cpu_str) / 1000.0 * 100  # Convert to percentage
                metrics.memory_usage = float(mem_str)
                
                # Get limits
                limits_cmd = f"kubectl describe pod {pod_name} -n {namespace} | grep -A 5 'Limits:'"
                limits_output = await self.execute_command(limits_cmd)
                # Parse limits (simplified)
                
        except Exception as e:
            logger.debug(f"Error getting metrics: {e}")
        
        return metrics

    async def tail_logs(self, pod_name: str, namespace: str = "default", 
                       callback: Callable[[LogEntry], Any] = None):
        """Stream logs from a pod in real-time."""
        cmd = f"kubectl logs -f {pod_name} -n {namespace} --tail=10"
        
        try:
            async with self.connection.create_process(cmd) as process:
                async for line in process.stdout:
                    if line:
                        log_entry = self.parse_log_line(line, pod_name)
                        if callback:
                            await callback(log_entry)
        except Exception as e:
            logger.error(f"Error streaming logs from {self.host}: {e}")

    def parse_logs(self, output: str, pod_name: str) -> List[LogEntry]:
        """Parse raw log output into structured log entries."""
        logs = []
        for line in output.strip().split('\n'):
            if line.strip():
                logs.append(self.parse_log_line(line, pod_name))
        return logs

    # Regex that matches a leading ISO-ish timestamp (with optional fractional
    # seconds and timezone) followed by an optional log-level keyword + colon.
    _TS_PREFIX_RE = re.compile(
        r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}"  # date+time
        r"(?:[.,]\d+)?"                               # fractional seconds
        r"(?:Z|[+-]\d{2}:\d{2})?"                     # timezone
        r"\s*"
    )
    _LEVEL_PREFIX_RE = re.compile(
        r"^(?:CRITICAL|ERROR|WARN(?:ING)?|INFO|DEBUG)\s*:?\s*",
        re.IGNORECASE,
    )

    def parse_log_line(self, line: str, pod_name: str) -> LogEntry:
        """Parse a single log line."""
        # Try to detect log level
        level = LogLevel.INFO
        if "CRITICAL" in line.upper():
            level = LogLevel.CRITICAL
        elif "ERROR" in line.upper():
            level = LogLevel.ERROR
        elif "WARN" in line.upper():
            level = LogLevel.WARNING
        elif "DEBUG" in line.upper():
            level = LogLevel.DEBUG

        # Try to extract timestamp
        timestamp = datetime.now()
        time_match = re.search(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', line)
        if time_match:
            try:
                timestamp = datetime.fromisoformat(time_match.group())
            except Exception:
                pass

        # Strip leading timestamp + level prefix so the UI doesn't show
        # them twice (they are already rendered from the structured fields).
        message = self._TS_PREFIX_RE.sub("", line)
        message = self._LEVEL_PREFIX_RE.sub("", message).strip() or line

        return LogEntry(
            timestamp=timestamp,
            level=level,
            message=message,
            pod_ip=self.host,
            pod_name=pod_name
        )

    async def close(self):
        """Close SSH connection."""
        if self.connection:
            self.connection.close()
            await self.connection.wait_closed()

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()