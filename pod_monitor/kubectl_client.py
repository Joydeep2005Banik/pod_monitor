"""
Kubectl Client - Local kubectl backend for pod monitoring.

Runs kubectl commands directly on the local machine via subprocess,
replacing the SSH-based approach for clusters where the user already
has kubectl access configured.
"""

import asyncio
import os
import re
import shutil
import logging
from pathlib import Path
from typing import List, Optional, Callable, Any
from datetime import datetime

from .models import LogEntry, LogLevel, PodMetrics

logger = logging.getLogger(__name__)


def _find_kubectl() -> Optional[str]:
    """Locate the kubectl binary, checking PATH and common install locations."""
    # 1. Standard PATH lookup
    found = shutil.which("kubectl")
    if found:
        return found

    # 2. Common non-PATH locations
    home = Path.home()
    candidates = [
        # minikube cache (versioned)
        *sorted(home.glob(".minikube/cache/linux/*/v*/kubectl"), reverse=True),
        home / ".local" / "bin" / "kubectl",
        home / "bin" / "kubectl",
        Path("/usr/local/bin/kubectl"),
        Path("/snap/bin/kubectl"),
    ]

    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)

    return None


class KubectlClient:
    """Fetch pod logs and metrics by shelling out to the local kubectl binary."""

    def __init__(self, pod_name: str, namespace: str = "default"):
        self.pod_name = pod_name
        self.namespace = namespace
        self._kubectl: str = ""  # resolved in connect()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """Verify that kubectl is reachable and the pod exists."""
        self._kubectl = _find_kubectl() or "kubectl"
        logger.debug("Using kubectl at: %s", self._kubectl)

        try:
            proc = await asyncio.create_subprocess_exec(
                self._kubectl, "get", "pod", self.pod_name,
                "-n", self.namespace, "--no-headers",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error(
                    "kubectl check failed for %s/%s: %s",
                    self.namespace, self.pod_name, stderr.decode().strip(),
                )
                return False

            logger.info("kubectl verified pod %s/%s", self.namespace, self.pod_name)
            return True

        except FileNotFoundError:
            logger.error("kubectl binary not found (tried: %s)", self._kubectl)
            return False
        except Exception as e:
            logger.error("kubectl connectivity check failed: %s", e)
            return False

    async def close(self):
        """No resources to release for local kubectl."""

    # ------------------------------------------------------------------
    # Log fetching
    # ------------------------------------------------------------------

    async def get_pod_logs(
        self, pod_name: str, tail: int = 100, namespace: str = "default"
    ) -> List[LogEntry]:
        """Fetch the last *tail* log lines from the pod."""
        cmd = [
            self._kubectl, "logs", pod_name,
            "-n", namespace,
            f"--tail={tail}",
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                logger.error("kubectl logs failed: %s", stderr.decode().strip())
                return []

            return self.parse_logs(stdout.decode(), pod_name)

        except Exception as e:
            logger.error("Error fetching logs for %s: %s", pod_name, e)
            return []

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    async def get_pod_metrics(
        self, pod_name: str, namespace: str = "default"
    ) -> dict:
        """Get CPU/memory metrics and pod metadata.

        Returns a dict with keys: ``metrics``, ``restarts``, ``node_name``,
        ``pod_ip``, ``phase``, ``image``, ``labels``.
        """
        metrics = PodMetrics()
        info: dict = {
            "metrics": metrics,
            "restarts": 0,
            "node_name": "",
            "pod_ip": "",
            "phase": "",
            "image": "",
            "labels": "",
        }

        # ── 1. Try kubectl top (requires metrics-server) ──
        top_cmd = [
            self._kubectl, "top", "pod", pod_name,
            "-n", namespace, "--no-headers",
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *top_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode == 0:
                # Output format: "pod-name   100m   500Mi"
                parts = stdout.decode().strip().split()
                if len(parts) >= 3:
                    cpu_str = parts[1].replace("m", "")
                    mem_str = parts[2].replace("Mi", "").replace("Gi", "")
                    metrics.cpu_usage = float(cpu_str) / 1000.0 * 100
                    metrics.memory_usage = float(mem_str)
            else:
                logger.debug("kubectl top unavailable (no metrics-server)")
        except Exception as e:
            logger.debug("Error getting kubectl top metrics: %s", e)

        # ── 2. Get resource limits, uptime, restarts, node, IP, phase, image, labels from pod spec ──
        spec_cmd = [
            self._kubectl, "get", "pod", pod_name,
            "-n", namespace,
            "-o", "jsonpath={.spec.containers[0].resources.limits.cpu}|"
                  "{.spec.containers[0].resources.limits.memory}|"
                  "{.spec.containers[0].resources.requests.cpu}|"
                  "{.spec.containers[0].resources.requests.memory}|"
                  "{.status.startTime}|"
                  "{.spec.nodeName}|"
                  "{.status.containerStatuses[0].restartCount}|"
                  "{.status.podIP}|"
                  "{.status.phase}|"
                  "{.spec.containers[0].image}|"
                  "{.metadata.labels.app}",
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *spec_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            if proc.returncode == 0:
                parts = stdout.decode().strip().split("|")
                # Pad to at least 11 fields so unpacking never fails
                parts += [""] * (11 - len(parts))
                (cpu_limit_str, mem_limit_str, _, _,
                 start_time_str, node_str, restarts_str,
                 pod_ip_str, phase_str, image_str, label_str) = parts[:11]

                # Parse CPU limit (e.g. "100m" → 100 millicores)
                if cpu_limit_str:
                    cpu_val = cpu_limit_str.replace("m", "")
                    try:
                        metrics.cpu_limit = float(cpu_val) / 1000.0 * 100
                    except ValueError:
                        pass

                # Parse memory limit (e.g. "64Mi")
                if mem_limit_str:
                    mem_val = mem_limit_str.replace("Mi", "").replace("Gi", "")
                    try:
                        val = float(mem_val)
                        if "Gi" in mem_limit_str:
                            val *= 1024
                        metrics.memory_limit = val
                    except ValueError:
                        pass

                # Calculate uptime from startTime
                if start_time_str:
                    try:
                        start = datetime.fromisoformat(
                            start_time_str.replace("Z", "+00:00")
                        )
                        metrics.uptime = (
                            datetime.now(start.tzinfo) - start
                        ).total_seconds()
                    except Exception:
                        pass

                info["node_name"] = node_str.strip()
                if restarts_str.strip().isdigit():
                    info["restarts"] = int(restarts_str.strip())
                info["pod_ip"] = pod_ip_str.strip()
                info["phase"] = phase_str.strip()
                info["image"] = image_str.strip()
                info["labels"] = label_str.strip()

        except Exception as e:
            logger.debug("Error getting pod spec: %s", e)

        return info

    # ------------------------------------------------------------------
    # Log parsing (mirrors SSHClient logic)
    # ------------------------------------------------------------------

    def parse_logs(self, output: str, pod_name: str) -> List[LogEntry]:
        """Parse raw log output into structured LogEntry objects."""
        logs: List[LogEntry] = []
        for line in output.strip().split("\n"):
            if line.strip():
                logs.append(self.parse_log_line(line, pod_name))
        return logs

    # Regex that matches a leading ISO-ish timestamp (with optional fractional
    # seconds and timezone) followed by an optional log-level keyword + colon.
    # Examples it strips:
    #   2026-07-23T13:18:10                 INFO: …
    #   2026-07-23T13:18:10.640Z            WARNING: …
    #   2026-07-23T13:18:10.640+05:30       ERROR …
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
        """Parse a single log line into a LogEntry."""
        # Detect level
        level = LogLevel.INFO
        upper = line.upper()
        if "CRITICAL" in upper:
            level = LogLevel.CRITICAL
        elif "ERROR" in upper:
            level = LogLevel.ERROR
        elif "WARN" in upper:
            level = LogLevel.WARNING
        elif "DEBUG" in upper:
            level = LogLevel.DEBUG

        # Extract timestamp
        timestamp = datetime.now()
        time_match = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", line)
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
            pod_ip=pod_name,   # no SSH host; use pod name as identifier
            pod_name=pod_name,
        )

    # ------------------------------------------------------------------
    # Context-manager support
    # ------------------------------------------------------------------

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
