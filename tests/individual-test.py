# test_components.py
"""
Test individual components separately.
"""

import asyncio
from pod_monitor.ssh_client import SSHClient
from pod_monitor.ai_analyzer import AIAnalyzer
from pod_monitor.utils import parse_timestamp, detect_log_level

async def test_ssh():
    """Test SSH connection."""
    client = SSHClient(
        host="192.168.1.100",
        username="root",
        password="password"
    )
    
    connected = await client.connect()
    print(f"SSH Connected: {connected}")
    
    if connected:
        logs = await client.get_pod_logs("test-pod", tail=10)
        print(f"Fetched {len(logs)} logs")
    
    await client.close()

def test_ai():
    """Test AI analyzer."""
    analyzer = AIAnalyzer(mock_mode=True)
    print("AI Analyzer initialized in mock mode")

def test_utils():
    """Test utility functions."""
    # Test timestamp parsing
    ts = parse_timestamp("2024-01-15T14:30:25Z")
    print(f"Parsed timestamp: {ts}")
    
    # Test log level detection
    level = detect_log_level("ERROR: Test")
    print(f"Detected level: {level}")

if __name__ == "__main__":
    print("Testing components...")
    test_utils()
    test_ai()
    # Uncomment to test SSH (requires real pod)
    # asyncio.run(test_ssh())