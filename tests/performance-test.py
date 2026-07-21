# test_performance.py
"""
Performance testing.
"""

import time
import asyncio
from pod_monitor.monitor import PodMonitor
from pod_monitor.config import Config

async def test_performance():
    """Test monitor performance."""
    config = Config()
    config.monitor.pods = ["192.168.1.100", "192.168.1.101", "192.168.1.102"]
    config.monitor.refresh_interval = 1
    
    monitor = PodMonitor(config)
    start = time.time()
    
    # Run for 10 cycles
    for _ in range(10):
        await monitor._monitor_pod("192.168.1.100")
    
    duration = time.time() - start
    print(f"10 cycles took {duration:.2f} seconds")
    print(f"Average: {duration/10:.2f} seconds per cycle")

if __name__ == "__main__":
    asyncio.run(test_performance())