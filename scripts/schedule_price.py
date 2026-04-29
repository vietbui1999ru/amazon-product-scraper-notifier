"""
Schedule a price check for a product at a future time.

Local (from project root):
    cd backend && python ../scripts/schedule_price.py --id 1 --price 39.99 --minutes 5
    cd backend && python ../scripts/schedule_price.py --url "https://amazon.com/dp/B07RW6Z692" --price 39.99 --minutes 10

Docker Compose:
    docker compose exec backend python scripts/schedule_price.py --id 1 --price 39.99 --minutes 5
    docker compose exec backend python scripts/schedule_price.py --url "https://amazon.com/dp/B07RW6Z692" --price 39.99 --minutes 10
"""

import argparse
import asyncio
import sys
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timedelta, timezone

_repo_root = Path(__file__).resolve().parent.parent / "backend"
if not _repo_root.exists():
    _repo_root = Path("/app")
sys.path.insert(0, str(_repo_root))

from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import Product, ScheduledPrice


async def main(product_id: int | None, url: str | None, price: float, minutes: int) -> None:
    settings = get_settings()

    if (product_id is None and url is None) or (product_id is not None and url is not None):
        print("Error: Provide exactly one of --id or --url")
        sys.exit(1)

    if price <= 0:
        print("Error: --price must be > 0")
        sys.exit(1)

    if minutes <= 0:
        print("Error: --minutes must be > 0")
        sys.exit(1)

    async with AsyncSessionLocal() as session:
        # Lookup product
        if product_id is not None:
            stmt = select(Product).where(Product.id == product_id)
        else:
            stmt = select(Product).where(Product.url == url)

        result = await session.execute(stmt)
        product = result.scalar_one_or_none()

        if not product:
            if product_id is not None:
                print(f"Product {product_id} not found.")
            else:
                print(f"Product with URL '{url}' not found.")
            return

        # Create scheduled price
        scheduled_for = datetime.now(timezone.utc) + timedelta(minutes=minutes)

        scheduled = ScheduledPrice(
            product_id=product.id,
            price=Decimal(str(price)),
            currency="USD",
            scheduled_for=scheduled_for,
        )

        session.add(scheduled)
        await session.commit()

        time_str = scheduled_for.strftime("%H:%M:%S")
        print(f"Scheduled: {product.name} -> ${price:.2f} at {time_str} ({minutes} min from now)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", type=int, default=None, help="Product ID")
    parser.add_argument("--url", type=str, default=None, help="Product URL")
    parser.add_argument("--price", type=float, required=True, help="Target price")
    parser.add_argument("--minutes", type=int, required=True, help="Minutes from now to schedule")
    args = parser.parse_args()

    asyncio.run(main(product_id=args.id, url=args.url, price=args.price, minutes=args.minutes))
