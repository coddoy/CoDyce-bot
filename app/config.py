"""Config loading and validation.

The whole app is driven by a single ``config.json`` file (see
``config.example.json`` at the repo root for the canonical shape).

Design choice: each player has their *own* Google Sheet and Discord
webhook, but every sheet is assumed to follow the same template, so the
cell locations for skills are defined once at the top level and reused
for every player.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when ``config.json`` is missing required structure."""


@dataclass(frozen=True)
class GoogleConfig:
    credentials_file: str = "credentials.json"


@dataclass(frozen=True)
class DiscordConfig:
    username: str | None = None
    avatar_url: str | None = None


@dataclass(frozen=True)
class SheetTemplate:
    """Cell locations for skills, shared across every player's sheet."""

    worksheet: str = "Sheet1"
    skills: dict[str, str] = field(default_factory=dict)

    def cell_for(self, skill: str) -> str:
        try:
            return self.skills[skill]
        except KeyError as exc:
            raise ConfigError(
                f"Skill {skill!r} is not defined in sheet_template.skills"
            ) from exc

    @property
    def skill_names(self) -> list[str]:
        return list(self.skills.keys())


@dataclass(frozen=True)
class PlayerConfig:
    name: str
    spreadsheet_id: str
    discord_webhook: str
    worksheet: str | None = None

    def worksheet_name(self, template: SheetTemplate) -> str:
        return self.worksheet or template.worksheet


@dataclass(frozen=True)
class AppConfig:
    google: GoogleConfig
    discord: DiscordConfig
    sheet_template: SheetTemplate
    players: dict[str, PlayerConfig]
    source_path: Path

    @property
    def player_names(self) -> list[str]:
        return list(self.players.keys())

    def player(self, name: str) -> PlayerConfig:
        try:
            return self.players[name]
        except KeyError as exc:
            raise ConfigError(f"Unknown player: {name!r}") from exc


def _require(d: dict[str, Any], key: str, ctx: str) -> Any:
    if key not in d:
        raise ConfigError(f"Missing required field {ctx}.{key!r}")
    return d[key]


def load_config(path: str | Path = "config.json") -> AppConfig:
    """Load and validate ``config.json``.

    Raises :class:`ConfigError` with a helpful message if anything in
    the file is missing or malformed.
    """
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise ConfigError(
            f"Config file not found: {cfg_path}. "
            f"Copy config.example.json to {cfg_path.name} and fill it in."
        )

    try:
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{cfg_path} is not valid JSON: {exc}") from exc

    google_raw = raw.get("google", {})
    google = GoogleConfig(
        credentials_file=google_raw.get("credentials_file", "credentials.json"),
    )

    discord_raw = raw.get("discord", {})
    discord = DiscordConfig(
        username=discord_raw.get("username"),
        avatar_url=discord_raw.get("avatar_url"),
    )

    template_raw = _require(raw, "sheet_template", "config")
    skills = _require(template_raw, "skills", "config.sheet_template")
    if not isinstance(skills, dict) or not skills:
        raise ConfigError(
            "config.sheet_template.skills must be a non-empty object "
            "of {skill_name: cell_address}"
        )
    template = SheetTemplate(
        worksheet=template_raw.get("worksheet", "Sheet1"),
        skills={str(k): str(v) for k, v in skills.items()},
    )

    players_raw = _require(raw, "players", "config")
    if not isinstance(players_raw, dict) or not players_raw:
        raise ConfigError("config.players must be a non-empty object")

    players: dict[str, PlayerConfig] = {}
    for name, p_raw in players_raw.items():
        if not isinstance(p_raw, dict):
            raise ConfigError(f"config.players.{name} must be an object")
        players[name] = PlayerConfig(
            name=name,
            spreadsheet_id=str(_require(p_raw, "spreadsheet_id", f"config.players.{name}")),
            discord_webhook=str(_require(p_raw, "discord_webhook", f"config.players.{name}")),
            worksheet=p_raw.get("worksheet"),
        )

    return AppConfig(
        google=google,
        discord=discord,
        sheet_template=template,
        players=players,
        source_path=cfg_path.resolve(),
    )


# --------------------------------------------------------------------------
# Demo / built-in config
# --------------------------------------------------------------------------
DEMO_SOURCE = Path("<built-in demo>")

DEMO_SEED: dict[str, dict[str, int]] = {
    "Aria":  {"Strength": 8,  "Dexterity": 14, "Intelligence": 12},
    "Borin": {"Strength": 16, "Dexterity": 10, "Intelligence": 9},
}


def make_demo_config() -> AppConfig:
    """Return a self-contained AppConfig (no files / network needed).

    Two demo characters, three skills each. The spreadsheet IDs and
    webhook URLs are placeholder strings — they are *never* called in
    demo mode because the app is wired to ``FakeSheetsClient`` and
    ``NullNotifier`` whenever this config is in use.
    """
    template = SheetTemplate(
        worksheet="Sheet1",
        skills={
            "Strength":     "B2",
            "Dexterity":    "B3",
            "Intelligence": "B4",
        },
    )
    players = {
        "Aria": PlayerConfig(
            name="Aria",
            spreadsheet_id="<demo>",
            discord_webhook="<demo>",
        ),
        "Borin": PlayerConfig(
            name="Borin",
            spreadsheet_id="<demo>",
            discord_webhook="<demo>",
        ),
    }
    return AppConfig(
        google=GoogleConfig(),
        discord=DiscordConfig(username="Skill Tracker (demo)"),
        sheet_template=template,
        players=players,
        source_path=DEMO_SOURCE,
    )


def is_demo_config(config: AppConfig) -> bool:
    return config.source_path == DEMO_SOURCE
