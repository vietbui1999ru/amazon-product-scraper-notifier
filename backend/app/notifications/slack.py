import aiohttp

from app.comparison.detector import PriceDropEvent
from app.notifications.base import AbstractNotifier
from app.notifications.errors import NotificationError

_TIMEOUT = aiohttp.ClientTimeout(total=10)


class SlackNotifier(AbstractNotifier):
    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url

    @property
    def name(self) -> str:
        return "slack"

    async def send(self, event: PriceDropEvent) -> None:
        payload = self._build_payload(event)
        try:
            async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
                async with session.post(self._webhook_url, json=payload) as response:
                    if response.status < 200 or response.status >= 300:
                        raise NotificationError(
                            f"Slack webhook returned non-2xx status: {response.status}"
                        )
        except aiohttp.ClientError as exc:
            raise NotificationError(f"Failed to reach Slack webhook: {exc}") from exc

    def _build_payload(self, event: PriceDropEvent) -> dict:
        safe_name = event.product_name.replace("<", "").replace(">", "").replace("|", "")
        return {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "Price Drop Alert 🎉",
                        "emoji": True,
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*<{event.product_url}|{safe_name}>*",
                    },
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Old Price*\n{event.currency} {event.old_price:.2f}"},
                        {"type": "mrkdwn", "text": f"*New Price*\n{event.currency} {event.new_price:.2f}"},
                        {"type": "mrkdwn", "text": f"*Savings*\n{event.currency} {event.drop_amount:.2f}"},
                        {"type": "mrkdwn", "text": f"*Drop %*\n{event.drop_percent:.1f}%"},
                    ],
                },
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": "Monitored by Price Drop Monitor",
                        }
                    ],
                },
            ]
        }
