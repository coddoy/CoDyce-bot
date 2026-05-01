"""Entry point: ``python main.py``.

Flags:
  --config PATH    Path to the JSON config file (default: config.json).
  --fake           Use an in-memory fake instead of Google Sheets / Discord.
                   Useful for trying out the UI before credentials are set up.
  --log-level X    Standard Python logging level (default: INFO).
"""

from __future__ import annotations

import argparse
import logging
import sys
from tkinter import messagebox

from app.config import ConfigError, load_config
from app.logic import AppService, NullNotifier
from app.sheets import FakeSheetsClient, SheetsClient
from app.ui import run_app


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Skill tracker control panel")
    parser.add_argument("--config", default="config.json", help="Path to config JSON")
    parser.add_argument(
        "--fake",
        action="store_true",
        help="Run with an in-memory fake backend (no Google / Discord calls)",
    )
    parser.add_argument("--log-level", default="INFO")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        msg = f"Config error: {exc}"
        logging.error(msg)
        try:
            messagebox.showerror("Config error", str(exc))
        except Exception:  # noqa: BLE001 - no display available
            pass
        return 2

    if args.fake:
        sheets = FakeSheetsClient(config)
        service = AppService(config, sheets, notifier=NullNotifier())
        logging.info("Running with fake backend (no Google / Discord calls)")
    else:
        service = AppService(config, SheetsClient(config))

    run_app(service)
    return 0


if __name__ == "__main__":
    sys.exit(main())
