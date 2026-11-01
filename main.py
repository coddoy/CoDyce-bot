"""Entry point: ``python main.py``.

By default this runs in **demo mode**: a built-in 2-character / 3-skill
config, an in-memory fake sheets backend, and a no-op Discord notifier.
The UI's activity log shows the message that *would* have been posted
to Discord, but no network calls are made.

Flip ``--live`` once you've finished setting up Google credentials and
Discord webhooks (see README) to enable the real backends.

Pass ``--bot`` to run the Discord slash-command bot instead of the UI.
This requires ``config.discord.bot_token`` to be set in your config.

Flags:
  --config PATH    Path to a JSON config file (default: config.json).
                   Only used when the file exists or when --live is set.
  --live           Use the real Google Sheets + Discord backends.
                   Requires --config to point at a valid file.
  --bot            Run the Discord slash-command bot (no UI). Requires
                   --config to point at a file with a real bot_token.
  --log-level X    Standard Python logging level (default: INFO).
  --log-dir PATH   Directory for rotating log files (default: logs/
                   next to this script).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from app.bot import HatBotError, run_bot
from app.config import (
    AppConfig,
    ConfigError,
    DEMO_SEED,
    is_demo_config,
    load_config,
    make_demo_config,
)
from app.hat_prefs import default_prefs_path
from app.logging_setup import DEFAULT_LOG_DIR, configure_logging
from app.logic import AppService, NullNotifier
from app.sheets import FakeSheetsClient, SheetsClient


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Skill tracker control panel")
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to config JSON (only required when using --live)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use the real Google Sheets + Discord backends "
        "(default is the offline demo mode)",
    )
    parser.add_argument(
        "--bot",
        action="store_true",
        help="Run the Discord slash-command bot instead of the UI. "
        "Requires --config to point at a file with discord.bot_token set.",
    )
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument(
        "--log-dir",
        default=str(DEFAULT_LOG_DIR),
        help="Directory for rotating log files "
        f"(default: {DEFAULT_LOG_DIR})",
    )
    return parser.parse_args(argv)


def _resolve_config(config_path: str, *, live: bool, bot: bool) -> AppConfig:
    """Pick the right AppConfig for the requested mode."""
    path = Path(config_path)

    if bot:
        if not path.exists():
            raise ConfigError(
                f"--bot requires a real config file. Not found: {path}"
            )
        return load_config(path)

    if live:
        if not path.exists():
            raise ConfigError(
                f"--live requires a real config file. Not found: {path}"
            )
        return load_config(path)

    if path.exists():
        logging.info("Loading config from %s (demo mode — no live calls)", path)
        return load_config(path)

    logging.info("No %s found; using built-in demo config.", path)
    return make_demo_config()


def _show_config_error(message: str) -> None:
    """Best-effort GUI error dialog; silent when Tk is unavailable."""
    try:
        from tkinter import messagebox

        messagebox.showerror("Config error", message)
    except Exception:  # noqa: BLE001 - no display / no Tk available
        pass


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    configure_logging(args.log_level, log_dir=args.log_dir)

    try:
        config = _resolve_config(args.config, live=args.live, bot=args.bot)
    except ConfigError as exc:
        logging.error("Config error: %s", exc)
        _show_config_error(str(exc))
        return 2

    if args.bot:
        try:
            run_bot(config, prefs_path=default_prefs_path(args.config))
        except HatBotError as exc:
            logging.error("Bot error: %s", exc)
            return 2
        return 0

    from app.ui import run_app

    if args.live:
        sheets = SheetsClient(config)
        service = AppService(config, sheets)
        demo_mode = False
    else:
        seed = DEMO_SEED if is_demo_config(config) else None
        sheets = FakeSheetsClient(config, seed=seed)
        service = AppService(config, sheets, notifier=NullNotifier())
        demo_mode = True

    run_app(service, demo_mode=demo_mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
