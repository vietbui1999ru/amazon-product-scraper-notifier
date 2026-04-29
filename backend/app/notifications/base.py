from abc import ABC, abstractmethod

from app.comparison.detector import PriceDropEvent


class AbstractNotifier(ABC):
    @abstractmethod
    async def send(self, event: PriceDropEvent) -> None:
        """Send notification for a price drop event."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name for this notifier."""
        ...
