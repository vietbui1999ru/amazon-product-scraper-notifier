"""
Demo script: inject a fake price drop for a tracked product and fire the notifier.

Local (venv active, from project root):
    cd backend && python ../scripts/demo_drop.py --list
    cd backend && python ../scripts/demo_drop.py --id 1 --pct 20

Docker Compose:
    docker compose exec backend python scripts/demo_drop.py --list
    docker compose exec backend python scripts/demo_drop.py --id 1 --pct 20

DATABASE_URL is read from env — docker compose sets it automatically.
For local dev, set it in .env (see .env.example; note port 5433).
"""

import argparse
import asyncio
import sys
from pathlib import Path
from decimal import Decimal

# Works whether run from backend/ (local) or /app (container)
_repo_root = Path(__file__).resolve().parent.parent / "backend"
if not _repo_root.exists():
    _repo_root = Path("/app")
sys.path.insert(0, str(_repo_root))

from sqlalchemy import select

from app.config import get_settings
from app.comparison.detector import PriceDropEvent
from app.database import AsyncSessionLocal
from app.models import PriceCheck, Product
from app.notifications.factory import create_notifier


async def get_products_with_prices(session) -> list[tuple[Product, PriceCheck | None]]:
    result = await session.execute(select(Product).order_by(Product.id))
    products = list(result.scalars().all())

    out = []
    for product in products:
        stmt = (
            select(PriceCheck)
            .where(
                PriceCheck.product_id == product.id,
                PriceCheck.scrape_success.is_(True),
                PriceCheck.price.is_not(None),
            )
            .order_by(PriceCheck.scraped_at.desc(), PriceCheck.id.desc())
            .limit(1)
        )
        r = await session.execute(stmt)
        out.append((product, r.scalar_one_or_none()))

    return out


async def inject_drop(product: Product, latest: PriceCheck, drop_pct: float, session) -> PriceCheck:
    old_price = Decimal(str(latest.price))
    new_price = (old_price * Decimal(str(1 - drop_pct / 100))).quantize(Decimal("0.01"))

    check = PriceCheck(
        product_id=product.id,
        price=float(new_price),
        currency=latest.currency,
        scrape_success=True,
        error_message=None,
        source="self",
    )
    session.add(check)
    await session.flush()
    return check, old_price, new_price


async def main(product_id: int | None, drop_pct: float, list_only: bool) -> None:
    settings = get_settings()
    notifier = create_notifier(settings)

    async with AsyncSessionLocal() as session:
        rows = await get_products_with_prices(session)

        if not rows:
            print("No products tracked yet. Add one via POST /api/products first.")
            return

        if list_only:
            print(f"{'ID':<5} {'Name':<40} {'Latest price'}")
            print("-" * 60)
            for product, check in rows:
                price_str = f"${check.price:.2f} {check.currency}" if check else "no data"
                print(f"{product.id:<5} {product.name[:40]:<40} {price_str}")
            return

        targets = [
            (p, c) for p, c in rows
            if (product_id is None or p.id == product_id) and c is not None
        ]

        if not targets:
            if product_id:
                print(f"Product {product_id} not found or has no price data yet.")
            else:
                print("No products with price data. Run the scheduler once first.")
            return

        for product, latest in targets:
            check, old_price, new_price = await inject_drop(product, latest, drop_pct, session)
            drop_amount = old_price - new_price
            drop_percent = float(drop_amount / old_price * 100)

            event = PriceDropEvent(
                product_id=product.id,
                product_name=product.name,
                product_url=product.url,
                old_price=old_price,
                new_price=new_price,
                drop_amount=drop_amount,
                drop_percent=drop_percent,
                currency=latest.currency,
            )

            await notifier.send(event)
            print(
                f"[{product.name}] ${old_price} → ${new_price} "
                f"(-{drop_percent:.1f}%) — notification sent"
            )

        await session.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", type=int, default=None, help="Product ID to drop")
    parser.add_argument("--pct", type=float, default=15.0, help="Drop percentage (default 15)")
    parser.add_argument("--list", action="store_true", dest="list_only", help="List products only")
    args = parser.parse_args()

    asyncio.run(main(product_id=args.id, drop_pct=args.pct, list_only=args.list_only))
