"""Allow running with `python -m pod_monitor`."""
import asyncio
from .main import main

asyncio.run(main())
