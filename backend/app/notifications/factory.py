from app.config import Settings
from app.notifications.base import AbstractNotifier
from app.notifications.console import ConsoleNotifier
from app.notifications.multi import MultiNotifier
from app.notifications.slack import SlackNotifier

_AVAILABLE_METHODS = ("console", "slack")


def _build_single(method: str, settings: Settings) -> AbstractNotifier:
    if method == "console":
        return ConsoleNotifier()
    if method == "slack":
        if not settings.slack_webhook_url:
            raise ValueError("notification_method includes 'slack' but slack_webhook_url is not set")
        return SlackNotifier(settings.slack_webhook_url)
    raise ValueError(
        f"Unknown notification_method '{method}'. "
        f"Available options: {', '.join(_AVAILABLE_METHODS)}"
    )


def create_notifier(settings: Settings) -> AbstractNotifier:
    """
    Accepts notification_method as a string or list of strings.

    "console"              → ConsoleNotifier
    "slack"                → SlackNotifier (requires slack_webhook_url)
    ["console", "slack"]   → MultiNotifier (fans out to both)
    """
    method = settings.notification_method
    methods: list[str] = [method] if isinstance(method, str) else list(method)
    notifiers = [_build_single(m, settings) for m in methods]
    return notifiers[0] if len(notifiers) == 1 else MultiNotifier(notifiers)
