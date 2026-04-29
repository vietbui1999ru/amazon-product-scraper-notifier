import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from decimal import Decimal

from app.comparison.detector import PriceDropEvent
from app.notifications.console import ConsoleNotifier
from app.notifications.slack import SlackNotifier
from app.notifications.errors import NotificationError
from app.notifications.factory import create_notifier
from app.config import Settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_event(**overrides) -> PriceDropEvent:
    defaults = dict(
        product_id=1,
        product_name="Widget Pro",
        product_url="https://example.com/widget",
        old_price=Decimal("99.99"),
        new_price=Decimal("79.99"),
        drop_amount=Decimal("20.00"),
        drop_percent=20.0,
        currency="USD",
    )
    defaults.update(overrides)
    return PriceDropEvent(**defaults)


def make_settings(**overrides) -> Settings:
    defaults = dict(
        database_url="postgresql+asyncpg://u:p@localhost/db",
        slack_webhook_url="",
        notification_method="console",
        products=[],
    )
    defaults.update(overrides)
    return Settings(**defaults)


# ---------------------------------------------------------------------------
# ConsoleNotifier
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_console_notifier_logs_and_prints(capsys):
    event = make_event()
    notifier = ConsoleNotifier()

    with patch("app.notifications.console.logger") as mock_logger:
        mock_logger.info = MagicMock()
        await notifier.send(event)

    captured = capsys.readouterr()
    assert "Widget Pro" in captured.out
    assert "99.99" in captured.out
    assert "79.99" in captured.out

    mock_logger.info.assert_called_once()
    call_kwargs = mock_logger.info.call_args
    assert call_kwargs[0][0] == "price_drop_detected"


# ---------------------------------------------------------------------------
# SlackNotifier — happy path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_slack_notifier_sends_correct_payload():
    event = make_event()
    notifier = SlackNotifier("https://hooks.slack.com/fake")

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_post = MagicMock()
    mock_post.__aenter__ = AsyncMock(return_value=mock_response)
    mock_post.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_post)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("app.notifications.slack.aiohttp.ClientSession", return_value=mock_session):
        await notifier.send(event)

    mock_session.post.assert_called_once()
    _, call_kwargs = mock_session.post.call_args
    payload = call_kwargs["json"]

    # Verify product name appears somewhere in the blocks
    blocks_text = str(payload["blocks"])
    assert "Widget Pro" in blocks_text


# ---------------------------------------------------------------------------
# SlackNotifier — non-2xx raises NotificationError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_slack_notifier_raises_on_non_2xx():
    event = make_event()
    notifier = SlackNotifier("https://hooks.slack.com/fake")

    mock_response = MagicMock()
    mock_response.status = 500
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_post = MagicMock()
    mock_post.__aenter__ = AsyncMock(return_value=mock_response)
    mock_post.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_post)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with patch("app.notifications.slack.aiohttp.ClientSession", return_value=mock_session):
        with pytest.raises(NotificationError, match="500"):
            await notifier.send(event)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def test_factory_returns_console_notifier():
    settings = make_settings(notification_method="console")
    notifier = create_notifier(settings)
    assert notifier.name == "console"


def test_factory_returns_slack_notifier_with_valid_url():
    settings = make_settings(
        notification_method="slack",
        slack_webhook_url="https://hooks.slack.com/T000/B000/xxx",
    )
    notifier = create_notifier(settings)
    assert notifier.name == "slack"


def test_factory_raises_for_slack_without_webhook_url():
    settings = make_settings(notification_method="slack", slack_webhook_url="")
    with pytest.raises(ValueError, match="slack_webhook_url"):
        create_notifier(settings)


def test_factory_raises_for_unknown_method():
    settings = make_settings(notification_method="email")
    with pytest.raises(ValueError, match="email"):
        create_notifier(settings)
