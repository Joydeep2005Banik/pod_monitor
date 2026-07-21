#!/usr/bin/env python3
"""
Test Pod Monitor with mock data (no real SSH connections needed)
"""

import asyncio
import random
from datetime import datetime
from pod_monitor.ui import PodMonitorUI
from pod_monitor.models import PodStatus, PodMetrics, LogEntry, LogLevel, Anomaly, Severity

class MockMonitor:
    """Mock monitor that generates fake data for testing."""
    
    def __init__(self):
        self.pods = self._create_mock_pods()
    
    def _create_mock_pods(self):
        pods = []
        for i in range(3):
            pod = PodStatus(
                ip=f"192.168.1.{100 + i}",
                name=f"test-pod-{i+1}",
                namespace="default",
                healthy=True,
                metrics=PodMetrics(
                    cpu_usage=random.uniform(10, 80),
                    memory_usage=random.uniform(100, 500),
                    error_rate=random.uniform(0, 5)
                )
            )
            # Add some mock logs
            pod.logs = self._generate_mock_logs()
            pod.error_count = len([l for l in pod.logs if l.level in (LogLevel.ERROR, LogLevel.CRITICAL)])
            pods.append(pod)
        return pods
    
    def _generate_mock_logs(self):
        log_messages = [
            "INFO: Application started successfully",
            "INFO: Processing request #1234",
            "WARNING: High memory usage detected",
            "ERROR: Database connection timeout",
            "INFO: Cache hit for key: user_123",
            "CRITICAL: Out of memory in worker pool",
            "INFO: Request completed in 45ms",
            "WARNING: Slow query detected (2.3s)",
            "ERROR: Failed to authenticate user",
            "INFO: Health check passed"
        ]
        
        logs = []
        for _ in range(20):
            msg = random.choice(log_messages)
            level = LogLevel.INFO
            if "ERROR" in msg:
                level = LogLevel.ERROR
            elif "CRITICAL" in msg:
                level = LogLevel.CRITICAL
            elif "WARNING" in msg:
                level = LogLevel.WARNING
            
            logs.append(LogEntry(
                timestamp=datetime.now(),
                level=level,
                message=msg,
                pod_ip="192.168.1.100"
            ))
        return logs
    
    async def get_all_pods(self):
        # Randomly update statuses for demo
        for pod in self.pods:
            pod.healthy = random.random() > 0.3
            pod.metrics.cpu_usage = random.uniform(10, 90)
            pod.metrics.memory_usage = random.uniform(100, 800)
            pod.error_count = random.randint(0, 5)
            
            # Randomly add anomalies
            if random.random() > 0.7:
                pod.anomalies = [
                    Anomaly(
                        id=f"test-{i}",
                        timestamp=datetime.now(),
                        severity=random.choice(list(Severity)),
                        description=f"Test anomaly {i} detected",
                        pod_ip=pod.ip,
                        suggestion="Check logs for details",
                        detected_by="mock"
                    ) for i in range(random.randint(1, 3))
                ]
            else:
                pod.anomalies = []
            
            # Add new logs
            new_logs = self._generate_mock_logs()[:5]
            pod.logs = (pod.logs + new_logs)[-50:]
        
        return self.pods

class MockUIMonitor:
    """Wrapper to make mock monitor compatible with UI."""
    
    def __init__(self):
        self.mock = MockMonitor()
        self.config = None
    
    async def get_all_pods(self):
        return await self.mock.get_all_pods()
    
    async def start(self):
        pass
    
    async def stop(self):
        pass

def run_mock_test():
    """Run the UI with mock data."""
    mock_monitor = MockUIMonitor()
    app = PodMonitorUI(mock_monitor)
    app.run()

if __name__ == "__main__":
    run_mock_test()