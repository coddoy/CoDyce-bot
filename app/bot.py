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
  4. (Optional) Put your server's ID in ``config.discord.guild_ids``
     (a JSON array, e.g. ``[12345, 67890]``) so the slash command
     syncs instantly to each listed guild while you're iterating;
     leave it empty/omitted to register globally (can take up to ~1
     hour to appear). The legacy single ``guild_id`` field is still
     accepted for backward compatibility.
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
    format_hat_help,
    format_hat_message,
    is_help_command,
    parse_hat_command,
    roll_hat,
)

log = logging.getLogger(__name__)

# Discord caps slash-command descriptions at 100 characters; keep the
# rendered string comfortably under that.
_DISCORD_DESCRIPTION_LIMIT = 100


class HatBotError(RuntimeError):
    """Raised when the bot is misconfigured or cannot start."""


def _hat_command_help(config: AppConfig) -> tuple[str, str]:
    """Build the slash command's short description and arg help text.

    Both strings adapt to which parsers are enabled in the config so
    users only see examples that will actually work. Discord caps
    both fields at 100 characters; we trim conservatively.
    """
    short_examples: list[str] = []
    long_examples: list[str] = []
    if config.hat.enable_hat_rolls:
        short_examples.extend(["52", "3 33", "hit"])
        long_examples.extend(["52", "3 33", "hit", "3 hit", "3hit"])
    if config.hat.enable_generic_rolls:
        short_examples.extend(["3d6+2", "2 4d8"])
        long_examples.extend(["d20", "3d6+2", "2 4d8", "3 d10+1"])

    if short_examples:
        description = (
            f"Roll dice (hat d{config.hat.die}). Ex: "
            f"{' | '.join(short_examples)}"
        )
    else:
        description = "Roll dice (no parsers enabled in config)."
    description = _truncate(description, _DISCORD_DESCRIPTION_LIMIT)

    if long_examples:
        args_help = (
            "Examples: "
            + ", ".join(f"`{e}`" for e in long_examples)
            + ". Use `help` for full usage."
        )
        args_help = _truncate(args_help, _DISCORD_DESCRIPTION_LIMIT)
    else:
        args_help = "Args after /hat (no rolls enabled). Try `help`."
    return description, args_help


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "\u2026"


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

    guild_objs = [discord.Object(id=gid) for gid in config.discord.guild_ids]

    @client.event
    async def on_ready() -> None:  # pragma: no cover - network side-effect
        try:
            if guild_objs:
                for guild_obj in guild_objs:
                    tree.copy_global_to(guild=guild_obj)
                    synced = await tree.sync(guild=guild_obj)
                    log.info(
                        "Synced %d command(s) to guild %s",
                        len(synced),
                        guild_obj.id,
                    )
            else:
                synced = await tree.sync()
                log.info("Synced %d global command(s)", len(synced))
        except Exception:  # noqa: BLE001
            log.exception("Failed to sync slash commands")
        log.info("Logged in as %s (id=%s)", client.user, getattr(client.user, "id", "?"))

    description, args_help = _hat_command_help(config)

    @tree.command(name="hat", description=description)
    @app_commands.describe(args=args_help)
    async def hat_cmd(
        interaction: "discord.Interaction", args: str
    ) -> None:  # pragma: no cover - network side-effect
        if is_help_command(args):
            help_text = format_hat_help(
                config.hat.die,
                enable_hat=config.hat.enable_hat_rolls,
                enable_generic=config.hat.enable_generic_rolls,
            )
            await interaction.response.send_message(help_text, ephemeral=True)
            return

        try:
            request = parse_hat_command(
                args,
                config.hat.die,
                enable_hat=config.hat.enable_hat_rolls,
                enable_generic=config.hat.enable_generic_rolls,
            )
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
    guild_label = (
        ",".join(str(g) for g in config.discord.guild_ids)
        if config.discord.guild_ids
        else "global"
    )
    log.info(
        "Starting bot (guild_ids=%s, die=d%d)…",
        guild_label,
        config.hat.die,
    )
    # ``client.run`` configures its own asyncio loop and signal handlers,
    # so this call blocks until the bot is shut down.
    client.run(token, log_handler=None)


__all__ = ["HatBotError", "build_client", "run_bot"]
