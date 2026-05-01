"""Discord webhook posting.

Module is named ``discord_notify`` (not ``discord``) to avoid shadowing
the ``discord.py`` package if it ever gets installed alongside.

The public surface is a single :func:`send_message` helper plus a tiny
:class:`DiscordNotifier` wrapper that pre-binds the username/avatar
overrides from the app config.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from .config import DiscordConfig

log = logging.getLogger(__name__)


class DiscordError(RuntimeError):
    """Raised when a webhook delivery cannot be completed."""


@dataclass(frozen=True)
class DiscordNotifier:
    config: DiscordConfig

    def send(self, webhook_url: str, content: str) -> None:
        send_message(
            webhook_url,
            content,
            username=self.config.username,
            avatar_url=self.config.avatar_url,
        )


def send_message(
    webhook_url: str,
    content: str,
    *,
    username: str | None = None,
    avatar_url: str | None = None,
    max_retries: int = 3,
    timeout: float = 10.0,
) -> None:
    """POST a plain-text message to a Discord webhook.

    Retries on transient failures and respects ``Retry-After`` on 429.
    Raises :class:`DiscordError` on permanent failure.
    """
    if not webhook_url:
        raise DiscordError("Empty webhook URL")
    if not content:
        raise DiscordError("Refusing to send an empty message")

    try:
        import requests
    except ImportError as exc:
        raise DiscordError(
            "The 'requests' package is required for Discord webhook delivery. "
            "Run: pip install -r requirements.txt"
        ) from exc

    payload: dict[str, object] = {"content": content[:2000]}
    if username:
        payload["username"] = username
    if avatar_url:
        payload["avatar_url"] = avatar_url

    last_error: str | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.post(webhook_url, json=payload, timeout=timeout)
        except requests.RequestException as exc:
            last_error = f"network error: {exc}"
            log.warning(
                "Webhook POST failed (attempt %d/%d): %s",
                attempt,
                max_retries,
                exc,
            )
            time.sleep(min(2 ** (attempt - 1), 5))
            continue

        if response.status_code == 204:
            return

        if response.status_code == 429:
            try:
                retry_after = float(response.json().get("retry_after", 1.0))
            except ValueError:
                retry_after = 1.0
            log.info("Rate limited by Discord, sleeping %.2fs", retry_after)
            time.sleep(retry_after)
            continue

        last_error = f"HTTP {response.status_code}: {response.text[:300]}"
        if 400 <= response.status_code < 500:
            break
        time.sleep(min(2 ** (attempt - 1), 5))

    raise DiscordError(
        f"Discord webhook delivery failed after {max_retries} attempts: {last_error}"
    )


def format_increment_message(player: str, skill: str, delta: int) -> str:
    """Standard message format used by the app."""
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta} {skill} for {player}"
