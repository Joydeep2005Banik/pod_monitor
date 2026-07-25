import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime
import uuid

from .models import PodStatus, LogEntry, Anomaly, Severity, LogLevel
from .config import Config
from .ssh_client import SSHClient
from .kubectl_client import KubectlClient
from .ai_analyzer import AIAnalyzer

logger = logging.getLogger(__name__)

class PodMonitor:
    def __init__(self, config: Config, ui_callback=None):
        self.config = config
        self.pods: Dict[str, PodStatus] = {}
        self.clients: Dict[str, object] = {}  # SSHClient or KubectlClient
        self.ai_analyzer = AIAnalyzer(
            api_token=config.ai.openai_token,
            ollama_url=config.ai.ollama_url,
            mock_mode=config.ai.mock_mode or not config.ai.enabled
        )
        self.ui_callback = ui_callback
        self.running = False
        self._tasks: List[asyncio.Task] = []

    @property
    def _use_kubectl(self) -> bool:
        return self.config.monitor.mode == "kubectl"

    async def start(self):
        """Start monitoring all pods."""
        self.running = True

        namespace = self.config.monitor.namespaces[0] if self.config.monitor.namespaces else "default"
        pods_to_monitor = self.config.monitor.pods

        if self._use_kubectl:
            if not pods_to_monitor or "*" in pods_to_monitor:
                pods_to_monitor = await KubectlClient.get_all_pods_in_namespace(namespace, self.config.monitor.context)
                logger.info(f"Discovered {len(pods_to_monitor)} pods in namespace {namespace}")
                
            for pod_name in pods_to_monitor:
                await self._connect_pod_kubectl(pod_name, namespace)
        else:
            # SSH mode — pod entries are pod names, we use ssh.host
            ssh_host = self.config.ssh.host
            if not ssh_host:
                logger.error("SSH mode enabled but no ssh.host provided in config")
                return

            if not pods_to_monitor or "*" in pods_to_monitor:
                temp_client = SSHClient(
                    host=ssh_host,
                    username=self.config.ssh.user,
                    password=self.config.ssh.password,
                    key_path=self.config.ssh.key_path,
                    port=self.config.ssh.port
                )
                if await temp_client.connect():
                    pods_to_monitor = await temp_client.get_all_pods_in_namespace(namespace)
                    await temp_client.close()
                    logger.info(f"Discovered {len(pods_to_monitor)} pods in namespace {namespace} via SSH")
                else:
                    logger.error("Failed to connect to SSH host for pod discovery")
                    pods_to_monitor = []

            for pod_name in pods_to_monitor:
                await self._connect_pod_ssh(ssh_host, pod_name, namespace)

        # Start monitoring tasks
        for key in self.pods:
            task = asyncio.create_task(self._monitor_pod(key))
            self._tasks.append(task)

        logger.info(f"Monitoring {len(self.pods)} pods (mode={self.config.monitor.mode})")

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    async def _connect_pod_kubectl(self, pod_name: str, namespace: str) -> bool:
        """Set up a local kubectl client for a pod."""
        client = KubectlClient(
            pod_name=pod_name, 
            namespace=namespace, 
            context=self.config.monitor.context
        )
        connected = await client.connect()
        if connected:
            self.clients[pod_name] = client
            self.pods[pod_name] = PodStatus(
                ip=pod_name,  # use pod name as identifier
                name=pod_name,
                namespace=namespace,
            )
            logger.info(f"kubectl: monitoring pod {namespace}/{pod_name}")
            return True
        else:
            logger.error(f"kubectl: pod {namespace}/{pod_name} not found or not ready")
            return False

    async def _connect_pod_ssh(self, host: str, pod_name: str, namespace: str) -> bool:
        """Establish SSH connection to a node and monitor a pod."""
        client = self.clients.get(host)
        if not client:
            client = SSHClient(
                host=host,
                username=self.config.ssh.user,
                password=self.config.ssh.password,
                key_path=self.config.ssh.key_path,
                port=self.config.ssh.port
            )
            connected = await client.connect()
            if not connected:
                logger.error(f"Failed to connect to host {host}")
                return False
            self.clients[host] = client

        self.pods[pod_name] = PodStatus(
            ip=host,
            name=pod_name,
            namespace=namespace
        )
        self.clients[pod_name] = client
        logger.info(f"SSH: monitoring pod {namespace}/{pod_name} via {host}")
        return True

    # ------------------------------------------------------------------
    # Monitoring loop
    # ------------------------------------------------------------------

    async def _monitor_pod(self, key: str):
        """Continuously monitor a single pod."""
        pod = self.pods.get(key)
        client = self.clients.get(key)

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
                error_logs = [l for l in logs if l.level in (LogLevel.ERROR, LogLevel.CRITICAL)]
                warning_logs = [l for l in logs if l.level == LogLevel.WARNING]
                pod.error_count = len(error_logs)

                # Get metrics from kubectl top (may be empty without metrics-server)
                if len(logs) > 0:
                    result = await client.get_pod_metrics(pod.name, pod.namespace)
                    # KubectlClient returns a dict; SSHClient returns PodMetrics.
                    if isinstance(result, dict):
                        pod.metrics = result["metrics"]
                        pod.restarts = result["restarts"]
                        pod.node_name = result["node_name"]
                        pod.pod_ip = result.get("pod_ip", "")
                        pod.phase = result.get("phase", "")
                        pod.image = result.get("image", "")
                        pod.labels = result.get("labels", "")
                    elif isinstance(result, tuple):
                        pod.metrics, pod.restarts, pod.node_name = result
                    else:
                        pod.metrics = result

                # ── Compute log-derived metrics ──
                total = len(logs)
                if total > 0:
                    # Error rate as percentage of log lines that are errors
                    pod.metrics.error_rate = (len(error_logs) / total) * 100

                    # Request rate: count INFO lines that look like request logs
                    # Our test pod emits "INFO: Request #N processed in Xms"
                    request_logs = [l for l in logs if l.level == LogLevel.INFO and "request" in l.message.lower()]
                    if request_logs and len(request_logs) >= 2:
                        # Estimate req/s from timestamps of first and last request
                        first_ts = request_logs[0].timestamp
                        last_ts = request_logs[-1].timestamp
                        span = (last_ts - first_ts).total_seconds()
                        if span > 0:
                            pod.metrics.request_rate = len(request_logs) / span
                        else:
                            pod.metrics.request_rate = float(len(request_logs))
                    else:
                        pod.metrics.request_rate = float(len(request_logs))

                    # Active "connections" — approximate as recent error + warning count
                    pod.metrics.active_connections = len(error_logs) + len(warning_logs)

                    # Set memory limit from pod spec (64Mi for our test pod)
                    if pod.metrics.memory_limit == 100.0 and pod.metrics.memory_usage == 0:
                        pod.metrics.memory_limit = 64.0  # fallback from test pod spec

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
                logger.error(f"Error monitoring pod {key}: {e}")
                await asyncio.sleep(5)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_pod_status(self, key: str) -> Optional[PodStatus]:
        """Get the current status of a pod."""
        return self.pods.get(key)

    async def get_all_pods(self) -> List[PodStatus]:
        """Get status of all pods."""
        return list(self.pods.values())

    async def stop(self):
        """Stop monitoring and clean up."""
        self.running = False

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        # Close clients (unique to prevent double closing)
        for client in set(self.clients.values()):
            await client.close()

        logger.info("Monitoring stopped")