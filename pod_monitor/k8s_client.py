import asyncio
import logging
from typing import List, Optional, Any
from datetime import datetime

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from .models import LogEntry, LogLevel, PodMetrics

logger = logging.getLogger(__name__)

def parse_k8s_memory(mem_str: str) -> float:
    """Parse k8s memory string (e.g. '1030Ki', '1.03Mi') and return value in MiB."""
    if not mem_str:
        return 0.0
    mem_str = str(mem_str).strip().strip('"\'')
    try:
        if mem_str.endswith("Ki"):
            return float(mem_str[:-2]) / 1024.0
        elif mem_str.endswith("Mi"):
            return float(mem_str[:-2])
        elif mem_str.endswith("Gi"):
            return float(mem_str[:-2]) * 1024.0
        elif mem_str.endswith("Ti"):
            return float(mem_str[:-2]) * 1024.0 * 1024.0
        elif mem_str.endswith("m"):
            return float(mem_str[:-1]) / (1024 * 1024 * 1000)
        elif mem_str.endswith("K"):
            return float(mem_str[:-1]) / 1000.0 * (1000 / 1024)
        else:
            # Assume raw bytes
            return float(mem_str) / (1024.0 * 1024.0)
    except ValueError:
        return 0.0


class KubernetesAPIClient:
    def __init__(self, context: Optional[str] = None):
        self.context = context
        self._connected = False
        self.v1 = None
        self.custom = None

    async def connect(self) -> bool:
        """Load kubeconfig and test connection."""
        try:
            config.load_kube_config(context=self.context)
            self.v1 = client.CoreV1Api()
            self.custom = client.CustomObjectsApi()
            
            # Test connection by fetching default namespace
            await asyncio.to_thread(self.v1.read_namespace, "default")
            self._connected = True
            logger.info("Connected to Kubernetes API via local kubeconfig.")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Kubernetes API: {e}")
            return False

    async def get_all_pods_in_namespace(self, namespace: str) -> List[str]:
        """Discover all pods in a namespace."""
        if not self._connected:
            return []
        try:
            pods = await asyncio.to_thread(self.v1.list_namespaced_pod, namespace)
            return [pod.metadata.name for pod in pods.items]
        except Exception as e:
            logger.error(f"Failed to discover pods in {namespace}: {e}")
            return []

    async def get_pod_status(self, pod_name: str, namespace: str = "default") -> dict:
        """Get pod metadata (restarts, phase, node, IP, uptime)."""
        info = {
            "restarts": None,
            "node_name": "unknown",
            "pod_ip": "unknown",
            "phase": "Unknown",
            "image": "unknown",
            "labels": "",
            "uptime": None,
            "error_message": None
        }
        if not self._connected:
            info["error_message"] = "Not connected to API"
            return info

        try:
            pod = await asyncio.to_thread(self.v1.read_namespaced_pod, pod_name, namespace)
            
            info["node_name"] = pod.spec.node_name or "unknown"
            info["pod_ip"] = pod.status.pod_ip or "unknown"
            phase = pod.status.phase or "Unknown"
            if pod.status.container_statuses:
                for cs in pod.status.container_statuses:
                    if cs.state and cs.state.waiting:
                        phase = cs.state.waiting.reason
                        break
                    if cs.state and cs.state.terminated and cs.state.terminated.exit_code != 0:
                        phase = cs.state.terminated.reason or "Error"
                        break
            
            info["phase"] = phase
            if pod.spec.containers and pod.spec.containers[0].image:
                info["image"] = pod.spec.containers[0].image
            
            if pod.metadata.labels:
                info["labels"] = ",".join(pod.metadata.labels.keys())
                
            if pod.status.container_statuses and len(pod.status.container_statuses) > 0:
                info["restarts"] = pod.status.container_statuses[0].restart_count
                
            if pod.metadata.creation_timestamp:
                start = pod.metadata.creation_timestamp
                info["uptime"] = (datetime.now(start.tzinfo) - start).total_seconds()
                
        except ApiException as e:
            info["error_message"] = f"API Error: {e.reason}"
        except Exception as e:
            info["error_message"] = f"Error: {str(e)}"
            
        return info



    async def get_pod_metrics(self, pod_name: str, namespace: str = "default", current_metrics: Optional[PodMetrics] = None) -> PodMetrics:
        """Get CPU and memory metrics via Metrics API."""
        metrics = PodMetrics()
        if not self._connected:
            return metrics
            
        try:
            # Get metrics object
            res = await asyncio.to_thread(
                self.custom.get_namespaced_custom_object,
                "metrics.k8s.io", "v1beta1", namespace, "pods", pod_name
            )
            
            if "containers" in res and len(res["containers"]) > 0:
                usage = res["containers"][0]["usage"]
                cpu_str = usage.get("cpu", "0n")
                mem_str = usage.get("memory", "0Ki")
                
                # Parse CPU (n = nanocores, m = millicores)
                if cpu_str.endswith("n"):
                    metrics.cpu_usage = float(cpu_str.replace("n", "")) / 1_000_000_000.0 * 100
                elif cpu_str.endswith("m"):
                    metrics.cpu_usage = float(cpu_str.replace("m", "")) / 1000.0 * 100
                else:
                    metrics.cpu_usage = float(cpu_str)
                    
                # Parse Memory
                metrics.memory_usage = parse_k8s_memory(mem_str)
                    
            # Also try to get limits from the pod spec
            pod = await asyncio.to_thread(self.v1.read_namespaced_pod, pod_name, namespace)
            if pod.spec.containers and pod.spec.containers[0].resources and pod.spec.containers[0].resources.limits:
                limits = pod.spec.containers[0].resources.limits
                cpu_limit = limits.get("cpu")
                mem_limit = limits.get("memory")
                
                if cpu_limit:
                    if cpu_limit.endswith("m"):
                        metrics.cpu_limit = float(cpu_limit.replace("m", "")) / 1000.0 * 100
                    else:
                        metrics.cpu_limit = float(cpu_limit) * 100
                        
                if mem_limit:
                    metrics.memory_limit = parse_k8s_memory(mem_limit)
                    
            if not metrics.memory_limit and pod.spec.node_name:
                # If NO limit is set, calculate percentage against total node memory capacity
                node = await asyncio.to_thread(self.v1.read_node, pod.spec.node_name)
                if node.status.capacity and 'memory' in node.status.capacity:
                    metrics.memory_limit = parse_k8s_memory(node.status.capacity['memory'])
                        
        except Exception as e:
            # Metrics API might not be installed or pod unavailable, leave metrics empty
            if current_metrics and current_metrics.memory_usage is not None:
                metrics.memory_usage = current_metrics.memory_usage
                metrics.memory_limit = current_metrics.memory_limit
                metrics.cpu_usage = current_metrics.cpu_usage
                metrics.cpu_limit = current_metrics.cpu_limit
                metrics.is_cached = True
            else:
                metrics.memory_usage = 0.0
            
        return metrics

    async def get_pod_logs(self, pod_name: str, tail: int = 100, namespace: str = "default") -> List[LogEntry]:
        """Fetch logs from a specific pod."""
        if not self._connected:
            return []
            
        try:
            output = await asyncio.to_thread(
                self.v1.read_namespaced_pod_log,
                pod_name, namespace, tail_lines=tail
            )
            # Reusing the parsing logic from kubectl_client
            from .kubectl_client import KubectlClient
            parser = KubectlClient(pod_name, namespace)
            return parser.parse_logs(output, pod_name)
        except Exception as e:
            logger.error(f"Error fetching logs for {pod_name}: {e}")
            return []

    async def close(self):
        pass
