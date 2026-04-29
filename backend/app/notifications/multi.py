import structlog

from app.comparison.detector import PriceDropEvent
from app.notifications.base import AbstractNotifier

log = structlog.get_logger(__name__)


class MultiNotifier(AbstractNotifier):
    """Fans out a single notification event to multiple notifiers in sequence."""

    def __init__(self, notifiers: list[AbstractNotifier]) -> None:
        self._notifiers = notifiers

    @property
    def name(self) -> str:
        return "+".join(n.name for n in self._notifiers)

    async def send(self, event: PriceDropEvent) -> None:
        for notifier in self._notifiers:
            try:
                await notifier.send(event)
            except Exception as exc:
                log.error("notifier.failed", notifier=notifier.name, error=str(exc))
