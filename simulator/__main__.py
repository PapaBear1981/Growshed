import asyncio
import contextlib

from .runner import main

with contextlib.suppress(KeyboardInterrupt):
    asyncio.run(main())
