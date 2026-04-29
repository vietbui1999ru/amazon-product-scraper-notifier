"""
Simulate a price walk backward in time for a product.

Local (from project root):
    cd backend && python ../scripts/simulate_price_walk.py --id 1 --days 30 --volatility 5

Docker Compose:
    docker compose exec backend python scripts/simulate_price_walk.py --id 1 --days 30 --volatility 5
"""

import argparse
import asyncio
import random
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

_repo_root = Path(__file__).resolve().parent.parent / "backend"
if not _repo_root.exists():
    _repo_root = Path("/app")
sys.path.insert(0, str(_repo_root))

from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models import PriceCheck, Product


async def main(product_id: int, days: int, volatility: float) -> None:
    settings = get_settings()

    async with AsyncSessionLocal() as session:
        # Get product
        stmt = select(Product).where(Product.id == product_id)
        result = await session.execute(stmt)
        product = result.scalar_one_or_none()

        if not product:
            print(f"Product {product_id} not found.")
            return

        # Get latest price
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
        result = await session.execute(stmt)
        latest = result.scalar_one_or_none()

        if not latest:
            print(f"No price data for product {product_id}. Run scheduler once first.")
            return

        # Generate price walk
        current_price = float(latest.price)
        now = datetime.now(timezone.utc)
        steps_per_day = 48  # 30-min intervals
        total_steps = days * steps_per_day

        checks = []
        for step_index in range(total_steps):
            # Random price change
            change_pct = random.uniform(-volatility, volatility)
            current_price *= (1 + change_pct / 100)
            current_price = max(current_price, 1.00)

            # Backward in time
            scraped_at = now - timedelta(minutes=step_index * 30)

            check = PriceCheck(
                product_id=product.id,
                price=round(current_price, 2),
                currency=latest.currency,
                scraped_at=scraped_at,
                scrape_success=True,
                error_message=None,
                notified=False,
                source="simulated",
            )
            checks.append(check)

        session.add_all(checks)
        await session.commit()

        print(f"Inserted {len(checks)} simulated checks for {product.name} over {days} days")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", type=int, required=True, help="Product ID")
    parser.add_argument("--days", type=int, default=30, help="Days back to generate (default 30)")
    parser.add_argument("--volatility", type=float, default=5, help="Max % change per step (default 5)")
    args = parser.parse_args()

    asyncio.run(main(product_id=args.id, days=args.days, volatility=args.volatility))
