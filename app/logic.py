"""Application service layer.

This is the *only* module the UI talks to. It owns the SheetsClient
and Discord notifier, exposes a small set of high-level operations
(load skills, apply increment) and emits structured results the UI
can render without knowing anything about gspread or HTTP.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from .config import AppConfig, PlayerConfig
from .discord_notify import (
    DiscordError,
    DiscordNotifier,
    format_increment_message,
)
from .hat import (
    HatCommandError,
    HatRequest,
    HatResult,
    NiceDailyTracker,
    format_hat_message_with_nice,
    parse_hat_command,
    roll_hat,
)
from .sheets import SheetsError

log = logging.getLogger(__name__)


class SheetsBackend(Protocol):
    """Subset of :class:`SheetsClient` we depend on (for fake/test swap)."""

    def load_player_skills(
        self, player: PlayerConfig, *, force: bool = False
    ) -> dict[str, int]: ...

    def increment_skill(
        self, player: PlayerConfig, skill: str, delta: int
    ) -> tuple[int, int]: ...

    def invalidate(self, player_name: str | None = None) -> None: ...


class NotifierBackend(Protocol):
    """Anything with a ``send(webhook_url, content)`` method."""

    def send(self, webhook_url: str, content: str) -> None: ...


@dataclass(frozen=True)
class IncrementResult:
    player: str
    skill: str
    cell: str
    delta: int
    old_value: int
    new_value: int
    sheet_updated: bool
    discord_sent: bool
    message: str
    discord_error: str | None = None


@dataclass(frozen=True)
class HatRollResult:
    """Outcome of a ``/hat`` command, ready for the UI to render."""

    player: str
    request: HatRequest
    result: HatResult
    message: str


class NullNotifier:
    """No-op notifier used by ``--fake`` mode and in tests."""

    def send(self, webhook_url: str, content: str) -> None:  # noqa: ARG002
        log.info("[NullNotifier] would post: %s", content)


class AppService:
    def __init__(
        self,
        config: AppConfig,
        sheets: SheetsBackend,
        notifier: NotifierBackend | None = None,
        nice_tracker: NiceDailyTracker | None = None,
    ) -> None:
        self.config = config
        self._sheets = sheets
        self._notifier: NotifierBackend = notifier or DiscordNotifier(config.discord)
        self._nice_tracker = nice_tracker or NiceDailyTracker()

    @property
    def player_names(self) -> list[str]:
        return self.config.player_names

    @property
    def skill_names(self) -> list[str]:
        return self.config.sheet_template.skill_names

    def load_skills(
        self, player_name: str, *, force: bool = False
    ) -> dict[str, int]:
        player = self.config.player(player_name)
        return self._sheets.load_player_skills(player, force=force)

    def apply_increment(
        self, player_name: str, skill: str, delta: int
    ) -> IncrementResult:
        """Update the sheet, then notify Discord.

        If the sheet update fails we raise :class:`SheetsError` and never
        notify. If Discord fails *after* a successful sheet write we
        still return a result, with ``discord_sent=False`` and the
        error captured — the source of truth is updated either way.
        """
        if delta == 0:
            raise ValueError("Increment must be non-zero")

        player = self.config.player(player_name)
        cell = self.config.sheet_template.cell_for(skill)
        old_value, new_value = self._sheets.increment_skill(player, skill, delta)

        message = format_increment_message(player.name, skill, delta)
        discord_sent = True
        discord_error: str | None = None
        try:
            self._notifier.send(player.discord_webhook, message)
        except DiscordError as exc:
            discord_sent = False
            discord_error = str(exc)
            log.warning("Discord delivery failed: %s", exc)

        return IncrementResult(
            player=player.name,
            skill=skill,
            cell=cell,
            delta=delta,
            old_value=old_value,
            new_value=new_value,
            sheet_updated=True,
            discord_sent=discord_sent,
            message=message,
            discord_error=discord_error,
        )

    def execute_hat(self, player_name: str, command_text: str) -> HatRollResult:
        """Parse, roll, and format a ``/hat`` command for ``player_name``.

        Raises :class:`HatCommandError` when the input cannot be parsed.
        Currently this does not post to Discord — webhooks can't reply
        to commands, so delivery is deferred to the future slash-command
        bot.
        """
        hat_cfg = self.config.hat
        request = parse_hat_command(
            command_text,
            hat_cfg.die,
            enable_hat=hat_cfg.enable_hat_rolls,
            enable_generic=hat_cfg.enable_generic_rolls,
        )
        result = roll_hat(request)
        message = format_hat_message_with_nice(
            player_name, result, self._nice_tracker
        )
        return HatRollResult(
            player=player_name,
            request=request,
            result=result,
            message=message,
        )


__all__ = [
    "AppService",
    "HatCommandError",
    "HatRollResult",
    "IncrementResult",
    "NotifierBackend",
    "NullNotifier",
    "SheetsBackend",
    "SheetsError",
]
