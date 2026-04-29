import os
from redis.asyncio import Redis

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        url = os.environ.get("REDIS_URL", "redis://localhost:6379")
        _redis = Redis.from_url(url, decode_responses=True)
    return _redis


_PRODUCT_TTL = 3600  # 1 hour — refreshed on every add/update


async def cache_product(product_id: int, url: str, name: str) -> None:
    r = get_redis()
    async with r.pipeline(transaction=False) as pipe:
        pipe.hset(f"product:{product_id}", mapping={"url": url, "name": name})
        pipe.expire(f"product:{product_id}", _PRODUCT_TTL)
        pipe.set(f"product_url:{url}", product_id, ex=_PRODUCT_TTL)
        await pipe.execute()


async def get_product_id_by_url(url: str) -> int | None:
    r = get_redis()
    val = await r.get(f"product_url:{url}")
    return int(val) if val else None


async def get_cached_product(product_id: int) -> dict | None:
    r = get_redis()
    data = await r.hgetall(f"product:{product_id}")
    return data if data else None


_PRODUCTS_KEY = "cache:products"
_PRODUCTS_TTL = 30


async def get_cached_products_list() -> str | None:
    r = get_redis()
    return await r.get(_PRODUCTS_KEY)


async def set_cached_products_list(data: str) -> None:
    r = get_redis()
    await r.set(_PRODUCTS_KEY, data, ex=_PRODUCTS_TTL)


async def invalidate_products_list() -> None:
    r = get_redis()
    await r.delete(_PRODUCTS_KEY)


async def acquire_force_lock(product_id: int) -> bool:
    """SET NX EX 60. Returns True if lock acquired (safe to scrape)."""
    r = get_redis()
    result = await r.set(f"force_lock:{product_id}", "1", nx=True, ex=60)
    return result is not None
