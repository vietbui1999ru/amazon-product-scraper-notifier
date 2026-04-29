import asyncio

_force_queue: asyncio.Queue[int] = asyncio.Queue(maxsize=500)


def get_force_queue() -> asyncio.Queue[int]:
    return _force_queue
