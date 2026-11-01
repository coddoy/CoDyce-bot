"""Discord slash-command bot.

Registers ``/hat`` and ``/hit`` as Discord slash commands and routes
them through the same parser/roller/formatter the demo UI uses
(:mod:`app.hat`), so the in-channel reply matches the demo output
line-for-line.

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
from pathlib import Path

from .config import AppConfig
from .hat import (
    HatCommandError,
    NiceDailyTracker,
    format_hat_help,
    format_hat_message_with_nice,
    format_hat_status,
    format_hat_status_all,
    format_set_dice_confirmation,
    is_help_command,
    is_set_dice_command,
    is_status_command,
    parse_hat_command,
    parse_hit_command,
    parse_set_dice_command,
    roll_hat,
    status_wants_all,
)
from .hat_prefs import DEFAULT_PREFS_FILENAME, HatUserPrefsStore

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


def _display_name(interaction: "discord.Interaction") -> str:
    return (
        interaction.user.display_name
        or interaction.user.name
        or "Roller"
    )


async def _send_roll_reply(
    interaction: "discord.Interaction",
    *,
    player: str,
    user_id: int,
    request: "HatRequest",
    prefs: HatUserPrefsStore,
    nice_tracker: NiceDailyTracker,
    log_label: str,
) -> None:
    """Roll dice and reply; shared by ``/hat`` and ``/hit``."""
    try:
        result = roll_hat(request)
        prefs.touch_display_name(user_id, player)
        message = format_hat_message_with_nice(
            player, result, nice_tracker
        )
        await interaction.response.send_message(message)
    except Exception as exc:  # noqa: BLE001
        log.exception("Unexpected %s failure", log_label)
        try:
            await interaction.response.send_message(
                f"\u274C Unexpected error: {exc}"
            )
        except Exception:  # noqa: BLE001
            await interaction.followup.send(
                f"\u274C Unexpected error: {exc}"
            )


def build_client(
    config: AppConfig,
    *,
    prefs_path: Path | None = None,
):
    """Construct a configured :class:`discord.Client` with slash commands.

    Registers ``/hat`` and ``/hit`` (when hat rolls are enabled).

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
    nice_tracker = NiceDailyTracker()
    prefs = HatUserPrefsStore(prefs_path or Path(DEFAULT_PREFS_FILENAME))
    prefs.load()

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
        user_id = interaction.user.id
        player = _display_name(interaction)
        hat_die = prefs.effective_die(user_id, config.hat.die)

        if is_help_command(args):
            help_text = format_hat_help(
                hat_die,
                enable_hat=config.hat.enable_hat_rolls,
                enable_generic=config.hat.enable_generic_rolls,
            )
            await interaction.response.send_message(help_text)
            return

        if is_set_dice_command(args):
            try:
                die = parse_set_dice_command(args)
            except HatCommandError as exc:
                await interaction.response.send_message(
                    f"\u274C `{args}` — {exc}"
                )
                return

            prefs.set_die(user_id, die, player)
            prefs.save()
            await interaction.response.send_message(
                format_set_dice_confirmation(player, die)
            )
            return

        if is_status_command(args):
            try:
                wants_all = status_wants_all(args)
            except HatCommandError as exc:
                await interaction.response.send_message(
                    f"\u274C `{args}` — {exc}"
                )
                return

            if wants_all:
                message = format_hat_status_all(prefs.list_overrides())
            else:
                message = format_hat_status(
                    player,
                    hat_die,
                    is_override=prefs.get_die(user_id) is not None,
                )
            await interaction.response.send_message(message)
            return

        try:
            request = parse_hat_command(
                args,
                hat_die,
                enable_hat=config.hat.enable_hat_rolls,
                enable_generic=config.hat.enable_generic_rolls,
            )
        except HatCommandError as exc:
            await interaction.response.send_message(
                f"\u274C `{args}` — {exc}"
            )
            return

        await _send_roll_reply(
            interaction,
            player=player,
            user_id=user_id,
            request=request,
            prefs=prefs,
            nice_tracker=nice_tracker,
            log_label="/hat",
        )

    if config.hat.enable_hat_rolls:

        @tree.command(
            name="hit",
            description=(
                "Roll d100 hit location (same as `/hat hit`). "
                "Ex: (empty) | 3 | 3hit | fireball"
            ),
        )
        @app_commands.describe(
            args=(
                "Optional count (1–9), sticky forms (`3hit`, `hit3`), "
                "or reason text. Empty = one roll."
            )
        )
        async def hit_cmd(
            interaction: "discord.Interaction",
            args: str = "",
        ) -> None:  # pragma: no cover - network side-effect
            user_id = interaction.user.id
            player = _display_name(interaction)

            try:
                request = parse_hit_command(
                    args,
                    enable_hat=config.hat.enable_hat_rolls,
                )
            except HatCommandError as exc:
                label = args if args else "(empty)"
                await interaction.response.send_message(
                    f"\u274C `{label}` — {exc}"
                )
                return

            await _send_roll_reply(
                interaction,
                player=player,
                user_id=user_id,
                request=request,
                prefs=prefs,
                nice_tracker=nice_tracker,
                log_label="/hit",
            )

    return client


def run_bot(
    config: AppConfig,
    *,
    prefs_path: Path | None = None,
) -> None:
    """Connect to Discord and serve slash commands until interrupted.

    Blocks the calling thread. Press Ctrl-C to stop.
    """
    token = config.discord.bot_token
    if not token or token.startswith("PASTE_"):
        raise HatBotError(
            "discord.bot_token is missing in config. "
            "See app/bot.py docstring for setup steps."
        )

    client = build_client(config, prefs_path=prefs_path)
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
    # ``log_handler=None`` skips discord.py's default StreamHandler so
    # ``discord.*`` loggers inherit the root handlers from configure_logging
    # (stderr + rotating file), including DEBUG gateway diagnostics.
    client.run(token, log_handler=None)


__all__ = ["HatBotError", "build_client", "run_bot"]
