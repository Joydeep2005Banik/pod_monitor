#!/usr/bin/env python3
"""
Pod Monitor - Main entry point
"""

import sys
import asyncio
import logging
from pathlib import Path

from .config import load_config
from .monitor import PodMonitor
from .ui import PodMonitorUI
from .models import PodStatus

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('pod_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

async def ui_callback(pod: PodStatus):
    """Callback function for UI updates."""
    # This can be used for additional logging or processing
    pass

async def main():
    """Main entry point."""
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser(description="Pod Monitor - AI-Powered CLI Monitoring")
    parser.add_argument("-c", "--config", default="config.yaml", help="Path to config file")
    parser.add_argument("--version", action="store_true", help="Show version")
    parser.add_argument("--generate-config", action="store_true", help="Generate default config")
    
    args = parser.parse_args()
    
    # Handle version
    if args.version:
        from . import __version__
        print(f"Pod Monitor v{__version__}")
        sys.exit(0)
    
    # Generate config if requested
    if args.generate_config:
        from .config import create_default_config
        create_default_config("config.yaml")
        print("Created default config.yaml")
        sys.exit(0)
    
    # Load configuration
    try:
        config = load_config(args.config)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        print(f"Error loading config: {e}")
        print("Use --generate-config to create a default config file")
        sys.exit(1)
    
    if not config.monitor.pods:
        logger.error("No pods configured. Please add pod names to config.yaml under monitor.pods")
        sys.exit(1)
    
    logger.info(f"Starting Pod Monitor with {len(config.monitor.pods)} pods (mode={config.monitor.mode})")
    logger.info(f"AI Analysis: {'Enabled' if config.ai.enabled else 'Disabled'}")
    logger.info(f"AI Provider: {config.ai.provider}")
    
    # Create monitor
    monitor = PodMonitor(config, ui_callback)
    
    # Create and run UI
    app = PodMonitorUI(monitor)
    
    try:
        await monitor.start()
        await app.run_async()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        await monitor.stop()
    except Exception as e:
        logger.error(f"Error: {e}")
        await monitor.stop()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())