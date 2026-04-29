import structlog

from app.comparison.detector import PriceDropEvent
from app.notifications.base import AbstractNotifier

logger = structlog.get_logger(__name__)


class ConsoleNotifier(AbstractNotifier):
    @property
    def name(self) -> str:
        return "console"

    async def send(self, event: PriceDropEvent) -> None:
        print(
            f"[PRICE DROP] {event.product_name}: "
            f"${event.old_price:.2f} → ${event.new_price:.2f} "
            f"({event.drop_percent:.1f}% off, save ${event.drop_amount:.2f})"
        )

        logger.info(
            "price_drop_detected",
            product_id=event.product_id,
            product_name=event.product_name,
            old_price=str(event.old_price),
            new_price=str(event.new_price),
            drop_percent=event.drop_percent,
        )
