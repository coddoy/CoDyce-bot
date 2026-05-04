"""Discord slash-command bot.

Registers ``/hat`` as a real Discord slash command and routes it through
the same parser/roller/formatter the demo UI uses (:mod:`app.hat`), so
the in-channel reply matches the demo output line-for-line.

Setup checklist:
  1. Create an application at https://discord.com/developers/applications
  2. Under "Bot", add a bot user and copy its **token**.
     -> paste into ``config.discord.bot_token``.
  3. Under "Installation" / "OAuth2 URL Generator", grant the bot the
     ``applications.commands`` scope, generate the install URL, and
     invite the bot to your server.
  4. (Optional) Put your server's ID in ``config.discord.guild_id`` so
     the slash command syncs instantly while you're iterating; leave it
     ``null`` to register globally (can take up to ~1 hour to appear).
  5. Run ``python main.py --bot``.

This module is **not** a replacement for the existing webhook posting
used by the skill-increment flow — the bot token authenticates a real
bot user (which can receive interactions) while the per-player webhooks
are still used for outbound skill-update messages.
"""

from __future__ import annotations

import logging

from .config import AppConfig
from .hat import (
    HatCommandError,
    format_hat_message,
    parse_hat_command,
    roll_hat,
)

log = logging.getLogger(__name__)


class HatBotError(RuntimeError):
    """Raised when the bot is misconfigured or cannot start."""


def build_client(config: AppConfig):
    """Construct a configured :class:`discord.Client` with ``/hat`` registered.

    Importing :mod:`discord` is deferred so the rest of the app (UI,
    sheets, etc.) still works in environments where discord.py isn't
    installed.
    """
    try:
        import discord
        from discord import app_commands
    except ImportError as exc:
        raise HatBotError(
            "discord.py is not installed. Run: pip install -r requirements.txt"
        ) from exc

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    guild_obj = (
        discord.Object(id=config.discord.guild_id)
        if config.discord.guild_id
        else None
    )

    @client.event
    async def on_ready() -> None:  # pragma: no cover - network side-effect
        try:
            if guild_obj is not None:
                tree.copy_global_to(guild=guild_obj)
                synced = await tree.sync(guild=guild_obj)
                log.info(
                    "Synced %d command(s) to guild %s",
                    len(synced),
                    config.discord.guild_id,
                )
            else:
                synced = await tree.sync()
                log.info("Synced %d global command(s)", len(synced))
        except Exception:  # noqa: BLE001
            log.exception("Failed to sync slash commands")
        log.info("Logged in as %s (id=%s)", client.user, getattr(client.user, "id", "?"))

    @tree.command(
        name="hat",
        description=(
            f"Roll the hat dice (default d{config.hat.die}). "
            "Examples: 52 | 3 33 | hit | 3 hit"
        ),
    )
    @app_commands.describe(
        args="Args after /hat. Examples: `52`, `3 33`, `hit`, `3 hit`, `3hit`."
    )
    async def hat_cmd(
        interaction: "discord.Interaction", args: str
    ) -> None:  # pragma: no cover - network side-effect
        try:
            request = parse_hat_command(args, config.hat.die)
        except HatCommandError as exc:
            await interaction.response.send_message(
                f"\u274C `{args}` — {exc}", ephemeral=True
            )
            return

        try:
            result = roll_hat(request)
            display_name = (
                interaction.user.display_name
                or interaction.user.name
                or "Roller"
            )
            message = format_hat_message(display_name, result)
            await interaction.response.send_message(message)
        except Exception as exc:  # noqa: BLE001
            log.exception("Unexpected /hat failure")
            try:
                await interaction.response.send_message(
                    f"\u274C Unexpected error: {exc}", ephemeral=True
                )
            except Exception:  # noqa: BLE001
                # If we already responded somewhere, fall back to followup.
                await interaction.followup.send(
                    f"\u274C Unexpected error: {exc}", ephemeral=True
                )

    return client


def run_bot(config: AppConfig) -> None:
    """Connect to Discord and serve slash commands until interrupted.

    Blocks the calling thread. Press Ctrl-C to stop.
    """
    token = config.discord.bot_token
    if not token or token.startswith("PASTE_"):
        raise HatBotError(
            "discord.bot_token is missing in config. "
            "See app/bot.py docstring for setup steps."
        )

    client = build_client(config)
    log.info(
        "Starting bot (guild_id=%s, die=d%d)…",
        config.discord.guild_id or "global",
        config.hat.die,
    )
    # ``client.run`` configures its own asyncio loop and signal handlers,
    # so this call blocks until the bot is shut down.
    client.run(token, log_handler=None)


__all__ = ["HatBotError", "build_client", "run_bot"]
