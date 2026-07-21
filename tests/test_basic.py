"""
Basic unit tests for Pod Monitor.
"""

import pytest
import asyncio
from datetime import datetime
from pod_monitor.models import (
    LogEntry, LogLevel, Anomaly, Severity, 
    PodStatus, PodMetrics
)
from pod_monitor.ai_analyzer import AIAnalyzer
from pod_monitor.utils import detect_log_level, calculate_error_rate

@pytest.fixture
def sample_logs():
    """Create sample logs for testing."""
    return [
        LogEntry(
            timestamp=datetime.now(),
            level=LogLevel.INFO,
            message="INFO: Test message",
            pod_ip="192.168.1.1"
        ),
        LogEntry(
            timestamp=datetime.now(),
            level=LogLevel.ERROR,
            message="ERROR: Something went wrong",
            pod_ip="192.168.1.1"
        ),
        LogEntry(
            timestamp=datetime.now(),
            level=LogLevel.CRITICAL,
            message="CRITICAL: System failure",
            pod_ip="192.168.1.1"
        )
    ]

def test_detect_log_level():
    """Test log level detection."""
    assert detect_log_level("ERROR: Database failed") == LogLevel.ERROR
    assert detect_log_level("WARNING: High memory") == LogLevel.WARNING
    assert detect_log_level("CRITICAL: Out of memory") == LogLevel.CRITICAL
    assert detect_log_level("INFO: Application started") == LogLevel.INFO

def test_calculate_error_rate(sample_logs):
    """Test error rate calculation."""
    rate = calculate_error_rate(sample_logs)
    assert rate == pytest.approx(66.67, 0.01)

def test_pod_status_health():
    """Test pod health status."""
    pod = PodStatus(
        ip="192.168.1.1",
        name="test-pod",
        healthy=True
    )
    assert pod.healthy == True
    
    pod.error_count = 5
    pod.healthy = pod.error_count < 3
    assert pod.healthy == False

@pytest.mark.asyncio
async def test_ai_analyzer_mock():
    """Test AI analyzer in mock mode."""
    analyzer = AIAnalyzer(mock_mode=True)
    
    logs = [
        LogEntry(
            timestamp=datetime.now(),
            level=LogLevel.ERROR,
            message="ERROR: Test error",
            pod_ip="192.168.1.1"
        )
    ]
    
    pod_status = PodStatus(
        ip="192.168.1.1",
        name="test-pod",
        error_count=1,
        total_logs=1
    )
    
    anomalies = await analyzer.analyze_logs(logs, pod_status)
    assert isinstance(anomalies, list)

if __name__ == "__main__":
    pytest.main(["-v"])