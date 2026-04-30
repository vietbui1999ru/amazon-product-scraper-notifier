import asyncio
import json
import re
from datetime import datetime
from decimal import Decimal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import (
    cache_product,
    get_cached_products_list,
    get_product_id_by_url,
    invalidate_products_list,
    set_cached_products_list,
)

log = structlog.get_logger(__name__)
from app.comparison.detector import PricePoint, detect_price_drop
from app.config import get_settings
from app.database import get_db
from app.models import PriceCheck
from app.notifications.factory import create_notifier
from app.scraper.amazon import AmazonScraper
from app.scraper.search import search_amazon
from app.storage.repository import ProductRepository

router = APIRouter(prefix="/api")

limiter = Limiter(key_func=get_remote_address)

_ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})")
_AMAZON_ASIN_URL_RE = re.compile(
    r"https?://(?:www\.)?amazon\.(?:com|co\.uk|de|fr|it|es|ca|com\.au|co\.jp|in|nl|pl|se|sg|com\.mx|com\.br)/.*?/dp/[A-Z0-9]{10}",
    re.IGNORECASE,
)


def _normalize_amazon_url(url: str) -> str:
    match = _ASIN_RE.search(url)
    return f"https://www.amazon.com/dp/{match.group(1)}" if match else url


class PriceCheckResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    price: float | None
    currency: str
    scraped_at: datetime
    scrape_success: bool
    error_message: str | None
    notified: bool
    source: str


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str
    name: str
    asin: str | None
    created_at: datetime
    image_url: str | None = None
    rating: str | None = None
    latest_price: float | None = None


class AddProductRequest(BaseModel):
    url: str
    name: str = Field(max_length=200)
    image_url: str | None = None
    rating: str | None = None
    initial_price: float | None = None


class DemoDropRequest(BaseModel):
    url: str
    price: float = Field(gt=0, description="New fake price (must be positive)")


@router.get("/products", response_model=list[ProductResponse])
async def list_products(session: AsyncSession = Depends(get_db)):
    try:
        cached = await get_cached_products_list()
        if cached is not None:
            return JSONResponse(content=json.loads(cached))
    except Exception as e:
        log.warning("cache.error", error=str(e))

    repo = ProductRepository(session)
    rows = await repo.get_all_products_with_latest_prices()

    responses = [
        ProductResponse(
            id=product.id,
            url=product.url,
            name=product.name,
            asin=product.asin,
            created_at=product.created_at,
            image_url=product.image_url,
            rating=product.rating,
            latest_price=float(check.price) if check and check.price else None,
        )
        for product, check in rows
    ]

    try:
        data = [r.model_dump(mode="json") for r in responses]
        await set_cached_products_list(json.dumps(data))
    except Exception as e:
        log.warning("cache.error", error=str(e))

    return responses


@router.get("/products/{product_id}/history", response_model=list[PriceCheckResponse])
async def get_product_history(
    product_id: int,
    limit: int = Query(default=100, ge=1, le=1000),
    session: AsyncSession = Depends(get_db),
) -> list[PriceCheckResponse]:
    repo = ProductRepository(session)

    product = await repo.get_product_by_id(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    history = await repo.get_price_history(product_id, limit=limit)
    return [PriceCheckResponse.model_validate(check) for check in history]


@router.get("/search")
@limiter.limit("1/second")
async def search_products(
    request: Request,
    q: str = Query(..., min_length=2, max_length=100),
    db: AsyncSession = Depends(get_db),
):
    async with AmazonScraper() as scraper:
        results = await search_amazon(q, scraper)
    return results


@router.post("/products", response_model=ProductResponse, status_code=201)
@limiter.limit("20/minute")
async def add_product(
    request: Request,
    body: AddProductRequest,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> ProductResponse:
    if not _AMAZON_ASIN_URL_RE.search(body.url):
        raise HTTPException(status_code=400, detail="URL must be a valid Amazon product URL containing a /dp/ASIN")

    normalized_url = _normalize_amazon_url(body.url)

    repo = ProductRepository(session)
    product, created = await repo.get_or_create_product(
        normalized_url, body.name,
        image_url=body.image_url,
        rating=body.rating,
    )
    if not created:
        response.status_code = 200

    initial_price = None
    if created and body.initial_price is not None:
        check = PriceCheck(
            product_id=product.id,
            price=body.initial_price,
            currency="USD",
            scrape_success=True,
            source="self",
        )
        session.add(check)
        initial_price = body.initial_price

    await session.commit()
    try:
        await invalidate_products_list()
    except Exception as e:
        log.warning("cache.invalidate_failed", error=str(e))
    await cache_product(product.id, product.url, product.name)

    last_check = await repo.get_last_successful_price(product.id)
    latest_price = initial_price or (float(last_check.price) if last_check and last_check.price else None)

    return ProductResponse(
        id=product.id,
        url=product.url,
        name=product.name,
        asin=product.asin,
        created_at=product.created_at,
        image_url=product.image_url,
        rating=product.rating,
        latest_price=latest_price,
    )


class UpdateProductImageRequest(BaseModel):
    image_url: str | None = Field(default=None, max_length=2048)

    @field_validator('image_url')
    @classmethod
    def validate_url_scheme(cls, v: str | None) -> str | None:
        if v is not None and not re.match(r'^https?://', v, re.IGNORECASE):
            raise ValueError('image_url must be an http or https URL')
        return v


@router.patch("/products/{product_id}/image", response_model=ProductResponse)
@limiter.limit("10/minute")
async def update_product_image(
    request: Request,
    product_id: int,
    body: UpdateProductImageRequest,
    session: AsyncSession = Depends(get_db),
) -> ProductResponse:
    repo = ProductRepository(session)
    product = await repo.update_product_image(product_id, body.image_url)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    await session.commit()
    try:
        await invalidate_products_list()
    except Exception as e:
        log.warning("cache.invalidate_failed", error=str(e))
    last_check = await repo.get_last_successful_price(product.id)
    latest_price = float(last_check.price) if last_check and last_check.price else None
    return ProductResponse(
        id=product.id, url=product.url, name=product.name, asin=product.asin,
        created_at=product.created_at, image_url=product.image_url,
        rating=product.rating, latest_price=latest_price,
    )


@router.post("/demo/drop", status_code=200)
@limiter.limit("10/minute")
async def demo_drop(
    request: Request,
    body: DemoDropRequest,
    session: AsyncSession = Depends(get_db),
):
    """Inject a fake price drop and fire the notifier. Redis-first product lookup."""
    if not _AMAZON_ASIN_URL_RE.search(body.url):
        raise HTTPException(status_code=400, detail="URL must be a valid Amazon product URL containing a /dp/ASIN")
    normalized_url = _normalize_amazon_url(body.url)
    repo = ProductRepository(session)

    product_id = await get_product_id_by_url(normalized_url)
    product = (
        await repo.get_product_by_id(product_id)
        if product_id is not None
        else await repo.get_product_by_url(normalized_url)
    )

    if product is None:
        raise HTTPException(
            status_code=404,
            detail="Product not found. Add it first via POST /api/products.",
        )

    previous = await repo.get_last_successful_price(product.id)

    check = PriceCheck(
        product_id=product.id,
        price=body.price,
        currency=previous.currency if previous else "USD",
        scrape_success=True,
        error_message=None,
        source="self",
    )
    session.add(check)
    await session.flush()

    drop_event = None
    if previous and previous.price is not None:
        drop_event = detect_price_drop(
            product_id=product.id,
            product_name=product.name,
            product_url=product.url,
            previous=PricePoint(price=Decimal(str(previous.price)), currency=previous.currency),
            current=PricePoint(price=Decimal(str(body.price)), currency=check.currency),
            threshold_percent=0.0,
            threshold_absolute=0.0,
        )
        if drop_event is not None:
            check.notified = True

    await session.commit()
    try:
        await invalidate_products_list()
    except Exception as e:
        log.warning("cache.invalidate_failed", error=str(e))

    notification_sent = False
    if drop_event is not None:
        try:
            notifier = create_notifier(get_settings())
            await notifier.send(drop_event)
            notification_sent = True
        except Exception as e:
            log.warning("notifier.send_failed", product=product.name, error=str(e))

    return {
        "product": product.name,
        "old_price": float(previous.price) if previous and previous.price else None,
        "new_price": body.price,
        "notification_sent": notification_sent,
    }


class ForceCheckRequest(BaseModel):
    product_ids: list[int] | None = None
    all: bool = False


@router.post("/products/force-check", status_code=202)
@limiter.limit("10/minute")
async def force_check(
    request: Request,
    body: ForceCheckRequest,
    session: AsyncSession = Depends(get_db),
):
    from asyncio import QueueFull

    from app.scheduler.queue import get_force_queue

    repo = ProductRepository(session)

    if body.all:
        products = await repo.get_all_products()
        ids = [p.id for p in products]
        not_found: list[int] = []
    elif body.product_ids is not None:
        if not body.product_ids:
            raise HTTPException(400, "product_ids must not be empty")
        requested = body.product_ids
        existing_products = await repo.get_products_by_ids(requested)
        ids = [p.id for p in existing_products]
        not_found = [pid for pid in requested if pid not in ids]
    else:
        raise HTTPException(400, "Provide product_ids or all=true")

    q = get_force_queue()
    queued = 0
    skipped_full = 0
    for pid in ids:
        try:
            q.put_nowait(pid)
            queued += 1
        except QueueFull:
            skipped_full += 1

    msg = "Scrape queued. Watch /api/logs for results."
    if skipped_full:
        msg += f" {skipped_full} skipped (queue full)."

    response: dict = {"queued": queued, "message": msg}
    if not body.all and not_found:
        response["not_found"] = not_found
    return response


class SchedulePriceRequest(BaseModel):
    product_id: int | None = None
    url: str | None = None
    price: float = Field(gt=0)
    minutes: int | None = Field(default=None, gt=0, le=525600)
    seconds: int | None = Field(default=None, gt=0, le=86400)


class ScheduledPriceResponse(BaseModel):
    id: int
    product: str
    price: float
    scheduled_for: datetime


@router.post("/scheduler/prices", response_model=ScheduledPriceResponse, status_code=201)
@limiter.limit("20/minute")
async def schedule_price(
    request: Request,
    body: SchedulePriceRequest,
    session: AsyncSession = Depends(get_db),
):
    from datetime import timezone
    from decimal import Decimal

    repo = ProductRepository(session)

    if body.product_id is not None:
        product = await repo.get_product_by_id(body.product_id)
    elif body.url is not None:
        product = await repo.get_product_by_url(body.url)
    else:
        raise HTTPException(400, "Provide product_id or url")

    if product is None:
        raise HTTPException(404, "Product not found")

    from datetime import timedelta

    if body.seconds is not None:
        delay = timedelta(seconds=body.seconds)
    elif body.minutes is not None:
        delay = timedelta(minutes=body.minutes)
    else:
        raise HTTPException(400, "Provide seconds or minutes")

    try:
        scheduled_for = datetime.now(timezone.utc) + delay
    except (OverflowError, ValueError) as exc:
        raise HTTPException(400, f"Invalid delay value: {exc}") from exc

    sp = await repo.create_scheduled_price(
        product_id=product.id,
        price=Decimal(str(body.price)),
        currency="USD",
        scheduled_for=scheduled_for,
    )
    await session.commit()

    return ScheduledPriceResponse(
        id=sp.id,
        product=product.name,
        price=float(sp.price),
        scheduled_for=sp.scheduled_for,
    )


@router.get("/scheduler/prices/pending")
async def list_pending_scheduled_prices(session: AsyncSession = Depends(get_db)):
    repo = ProductRepository(session)
    rows = await repo.get_pending_scheduled_prices_with_products()

    return [
        {
            "id": sp.id,
            "product_id": sp.product_id,
            "product": product.name,
            "price": float(sp.price),
            "currency": sp.currency,
            "scheduled_for": sp.scheduled_for,
            "created_at": sp.created_at,
        }
        for sp, product in rows
    ]


@router.delete("/scheduler/prices/{scheduled_id}", status_code=200)
@limiter.limit("30/minute")
async def cancel_scheduled_price(
    request: Request,
    scheduled_id: int,
    session: AsyncSession = Depends(get_db),
):
    from datetime import timezone

    repo = ProductRepository(session)
    now = datetime.now(timezone.utc)
    cancelled = await repo.cancel_scheduled_price(scheduled_id, "manual", now)

    if not cancelled:
        raise HTTPException(404, "Scheduled price not found or already settled")

    await session.commit()
    return {"cancelled": scheduled_id}


@router.get("/logs")
async def stream_logs(request: Request):
    """SSE stream of structured log events. Open in browser or EventSource."""
    from app.logbus import subscribe, unsubscribe

    async def event_stream():
        q = subscribe()
        try:
            yield "retry: 2000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    line = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {line}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            unsubscribe(q)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
