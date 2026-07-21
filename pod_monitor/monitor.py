import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime
import uuid

from .models import PodStatus, LogEntry, Anomaly, Severity, LogLevel
from .config import Config
from .ssh_client import SSHClient
from .ai_analyzer import AIAnalyzer

logger = logging.getLogger(__name__)

class PodMonitor:
    def __init__(self, config: Config, ui_callback=None):
        self.config = config
        self.pods: Dict[str, PodStatus] = {}
        self.ssh_clients: Dict[str, SSHClient] = {}
        self.ai_analyzer = AIAnalyzer(
            api_token=config.ai.openai_token,
            ollama_url=config.ai.ollama_url,
            mock_mode=not config.ai.enabled
        )
        self.ui_callback = ui_callback
        self.running = False
        self._tasks: List[asyncio.Task] = []

    async def start(self):
        """Start monitoring all pods."""
        self.running = True
        
        # Initialize connections
        for ip in self.config.monitor.pods:
            await self._connect_pod(ip)
        
        # Start monitoring tasks
        for ip in self.pods:
            task = asyncio.create_task(self._monitor_pod(ip))
            self._tasks.append(task)
        
        logger.info(f"Monitoring {len(self.pods)} pods")

    async def _connect_pod(self, ip: str) -> bool:
        """Establish SSH connection to a pod."""
        client = SSHClient(
            host=ip,
            username=self.config.ssh.user,
            password=self.config.ssh.password,
            key_path=self.config.ssh.key_path,
            port=self.config.ssh.port
        )
        
        connected = await client.connect()
        if connected:
            self.ssh_clients[ip] = client
            self.pods[ip] = PodStatus(
                ip=ip,
                name=f"pod-{ip.replace('.', '-')}",
                namespace="default"
            )
            logger.info(f"Connected to pod {ip}")
            return True
        else:
            logger.error(f"Failed to connect to pod {ip}")
            return False

    async def _monitor_pod(self, ip: str):
        """Continuously monitor a single pod."""
        pod = self.pods.get(ip)
        client = self.ssh_clients.get(ip)
        
        if not pod or not client:
            return
        
        while self.running:
            try:
                # Fetch logs
                logs = await client.get_pod_logs(
                    pod.name,
                    tail=self.config.monitor.log_lines_to_fetch,
                    namespace=pod.namespace
                )
                
                # Update pod status
                pod.logs = logs
                pod.total_logs += len(logs)
                pod.last_check = datetime.now()
                
                # Update error count
                old_error_count = pod.error_count
                pod.error_count = len([l for l in logs if l.level in (LogLevel.ERROR, LogLevel.CRITICAL)])
                
                # Get metrics
                if len(logs) > 0:
                    pod.metrics = await client.get_pod_metrics(pod.name, pod.namespace)
                
                # Analyze logs for anomalies
                anomalies = await self.ai_analyzer.analyze_logs(logs, pod)
                pod.anomalies = anomalies
                
                # Check if pod is healthy
                pod.healthy = pod.error_count < self.config.monitor.anomaly_threshold and len(anomalies) == 0
                
                # Trigger UI update
                if self.ui_callback:
                    await self.ui_callback(pod)
                
                # Wait before next check
                await asyncio.sleep(self.config.monitor.refresh_interval)
                
            except Exception as e:
                logger.error(f"Error monitoring pod {ip}: {e}")
                await asyncio.sleep(5)

    async def get_pod_status(self, ip: str) -> Optional[PodStatus]:
        """Get the current status of a pod."""
        return self.pods.get(ip)

    async def get_all_pods(self) -> List[PodStatus]:
        """Get status of all pods."""
        return list(self.pods.values())

    async def stop(self):
        """Stop monitoring and clean up."""
        self.running = False
        
        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
        
        # Close SSH connections
        for client in self.ssh_clients.values():
            await client.close()
        
        logger.info("Monitoring stopped")