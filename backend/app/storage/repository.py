import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PriceCheck, Product, ScheduledPrice

_ASIN_RE = re.compile(r"/dp/([A-Z0-9]{10})")


def _extract_asin(url: str) -> str | None:
    match = _ASIN_RE.search(url)
    return match.group(1) if match else None


class ProductRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create_product(
        self,
        url: str,
        name: str,
        image_url: str | None = None,
        rating: str | None = None,
    ) -> tuple[Product, bool]:
        """Return (product, created). `created` is True when a new row was inserted.

        image_url and rating are only written on creation; existing products are
        not overwritten so the method stays idempotent.
        """
        result = await self._session.execute(select(Product).where(Product.url == url))
        existing = result.scalar_one_or_none()
        if existing:
            return existing, False

        product = Product(
            url=url,
            name=name,
            asin=_extract_asin(url),
            image_url=image_url,
            rating=rating,
        )
        self._session.add(product)
        try:
            await self._session.flush()
            return product, True
        except IntegrityError:
            # Two concurrent requests raced — re-fetch the winner's row.
            await self._session.rollback()
            result = await self._session.execute(select(Product).where(Product.url == url))
            existing = result.scalar_one_or_none()
            if existing is None:
                raise  # extremely rare: race winner rolled back too
            return existing, False

    async def record_price_check(
        self,
        product: Product,
        price: float | None,
        currency: str,
        success: bool,
        error_message: str | None = None,
        source: str = "amazon",
    ) -> PriceCheck:
        check = PriceCheck(
            product_id=product.id,
            price=price,
            currency=currency,
            scrape_success=success,
            error_message=error_message,
            source=source,
        )
        self._session.add(check)
        await self._session.flush()
        return check

    async def get_last_successful_price(self, product_id: int) -> PriceCheck | None:
        stmt = (
            select(PriceCheck)
            .where(
                PriceCheck.product_id == product_id,
                PriceCheck.scrape_success.is_(True),
                PriceCheck.price.is_not(None),
            )
            .order_by(PriceCheck.scraped_at.desc(), PriceCheck.id.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_price_history(
        self, product_id: int, limit: int = 100
    ) -> list[PriceCheck]:
        stmt = (
            select(PriceCheck)
            .where(PriceCheck.product_id == product_id)
            .order_by(PriceCheck.scraped_at.desc(), PriceCheck.id.desc())
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_all_products(self) -> list[Product]:
        result = await self._session.execute(
            select(Product).order_by(Product.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_all_products_with_latest_prices(
        self,
    ) -> list[tuple[Product, "PriceCheck | None"]]:
        """Return all products with their latest successful price in a single query."""
        latest_subq = (
            select(
                PriceCheck.product_id,
                func.max(PriceCheck.id).label("max_id"),
            )
            .where(
                PriceCheck.scrape_success.is_(True),
                PriceCheck.price.is_not(None),
            )
            .group_by(PriceCheck.product_id)
            .subquery()
        )
        stmt = (
            select(Product, PriceCheck)
            .outerjoin(latest_subq, Product.id == latest_subq.c.product_id)
            .outerjoin(PriceCheck, PriceCheck.id == latest_subq.c.max_id)
            .order_by(Product.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return [(prod, check) for prod, check in result.all()]

    async def get_products_by_ids(self, ids: list[int]) -> list[Product]:
        """Fetch multiple products by ID in a single query."""
        if not ids:
            return []
        result = await self._session.execute(
            select(Product).where(Product.id.in_(ids))
        )
        return list(result.scalars().all())

    async def get_product_by_id(self, product_id: int) -> Product | None:
        result = await self._session.execute(
            select(Product).where(Product.id == product_id)
        )
        return result.scalar_one_or_none()

    async def update_product_image(self, product_id: int, image_url: str | None) -> Product | None:
        product = await self.get_product_by_id(product_id)
        if product is None:
            return None
        product.image_url = image_url
        await self._session.flush()
        return product

    async def get_previous_successful_price(
        self, product_id: int, exclude_id: int
    ) -> PriceCheck | None:
        stmt = (
            select(PriceCheck)
            .where(
                PriceCheck.product_id == product_id,
                PriceCheck.scrape_success.is_(True),
                PriceCheck.price.is_not(None),
                PriceCheck.id != exclude_id,
            )
            .order_by(PriceCheck.scraped_at.desc(), PriceCheck.id.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_product_by_url(self, url: str) -> Product | None:
        result = await self._session.execute(
            select(Product).where(Product.url == url)
        )
        return result.scalar_one_or_none()

    async def mark_notified(self, price_check_id: int) -> None:
        result = await self._session.execute(
            select(PriceCheck).where(PriceCheck.id == price_check_id)
        )
        check = result.scalar_one()
        check.notified = True
        await self._session.flush()

    # ── ScheduledPrice methods ────────────────────────────────────────────────

    def _pending_filter(self):
        """Reusable filter: applied_at IS NULL AND cancelled_at IS NULL."""
        return and_(
            ScheduledPrice.applied_at.is_(None),
            ScheduledPrice.cancelled_at.is_(None),
        )

    async def create_scheduled_price(
        self,
        product_id: int,
        price: Decimal,
        currency: str,
        scheduled_for: datetime,
    ) -> ScheduledPrice:
        row = ScheduledPrice(
            product_id=product_id,
            price=price,
            currency=currency,
            scheduled_for=scheduled_for,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_pending_scheduled_prices_due(self, now: datetime) -> list[ScheduledPrice]:
        """Return all pending scheduled prices where scheduled_for <= now."""
        stmt = select(ScheduledPrice).where(
            self._pending_filter(),
            ScheduledPrice.scheduled_for <= now,
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_pending_scheduled_prices(self) -> list[ScheduledPrice]:
        """Return all pending scheduled prices (for API listing)."""
        stmt = select(ScheduledPrice).where(self._pending_filter()).order_by(
            ScheduledPrice.scheduled_for.asc()
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_pending_scheduled_prices_with_products(
        self,
    ) -> list[tuple[ScheduledPrice, Product]]:
        """Return pending scheduled prices joined with their products in one query."""
        stmt = (
            select(ScheduledPrice, Product)
            .join(Product, ScheduledPrice.product_id == Product.id)
            .where(self._pending_filter())
            .order_by(ScheduledPrice.scheduled_for.asc())
        )
        result = await self._session.execute(stmt)
        return [(sp, prod) for sp, prod in result.all()]

    async def get_scheduled_price_by_id(self, scheduled_id: int) -> ScheduledPrice | None:
        result = await self._session.execute(
            select(ScheduledPrice).where(ScheduledPrice.id == scheduled_id)
        )
        return result.scalar_one_or_none()

    async def cancel_pending_scheduled_prices(
        self, product_id: int, reason: str, now: datetime
    ) -> None:
        """Cancel all pending scheduled prices for a product (atomic UPDATE)."""
        stmt = (
            update(ScheduledPrice)
            .where(
                ScheduledPrice.product_id == product_id,
                ScheduledPrice.applied_at.is_(None),
                ScheduledPrice.cancelled_at.is_(None),
            )
            .values(cancelled_at=now, cancel_reason=reason)
        )
        await self._session.execute(stmt)

    async def cancel_scheduled_price(
        self, scheduled_id: int, reason: str, now: datetime
    ) -> bool:
        """Atomically cancel a specific scheduled price. Returns False if not found or already settled."""
        stmt = (
            update(ScheduledPrice)
            .where(
                ScheduledPrice.id == scheduled_id,
                ScheduledPrice.applied_at.is_(None),
                ScheduledPrice.cancelled_at.is_(None),
            )
            .values(cancelled_at=now, cancel_reason=reason)
            .returning(ScheduledPrice.id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    # ── Maintenance ──────────────────────────────────────────────────────────

    async def prune_price_history(self, product_id: int, keep: int = 500) -> int:
        """Delete all but the most recent `keep` rows for a product. Returns deleted count."""
        keep_ids_subq = (
            select(PriceCheck.id)
            .where(PriceCheck.product_id == product_id)
            .order_by(PriceCheck.scraped_at.desc(), PriceCheck.id.desc())
            .limit(keep)
            .subquery()
        )
        result = await self._session.execute(
            delete(PriceCheck).where(
                PriceCheck.product_id == product_id,
                PriceCheck.id.notin_(select(keep_ids_subq.c.id)),
            )
        )
        return result.rowcount

    async def delete_settled_scheduled_prices(self, older_than_days: int = 30) -> int:
        """Delete applied/cancelled scheduled prices older than `older_than_days`. Returns deleted count."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        result = await self._session.execute(
            delete(ScheduledPrice).where(
                or_(
                    ScheduledPrice.applied_at <= cutoff,
                    ScheduledPrice.cancelled_at <= cutoff,
                )
            )
        )
        return result.rowcount
