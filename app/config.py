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
    """Settings for the Discord bot.

    ``guild_ids`` is the list of Discord server (guild) IDs the
    ``/hat`` slash command is synced to on startup. Syncing per-guild
    is near-instant; an empty list registers the command globally,
    which can take up to ~1 hour to appear.

    For backward compatibility ``config.discord.guild_id`` (a single
    integer) is still accepted and merged into ``guild_ids``.
    """

    username: str | None = None
    avatar_url: str | None = None
    bot_token: str | None = None
    guild_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class HatConfig:
    """Settings for the ``/hat`` dice-rolling command.

    ``die`` is the size of the standard die rolled when the command
    is invoked with numeric args (e.g. ``/hat 52`` rolls 1d{die}+52).
    The ``hit`` keyword always rolls d100 regardless of this value.

    Two parsers can be enabled independently:

    * ``enable_hat_rolls`` — the game-system-specific shorthand
      (``52``, ``3 33``, ``hit``, ``3 hit``, ``5hit``, …) that rolls
      ``1d{die}+modifier`` and uses the ``hit`` keyword for d100.
    * ``enable_generic_rolls`` — the universal ``Z XdY+/-#`` form
      (``3d6``, ``2 4d8+1``, ``d20 -3``, …) where Z is the number of
      groups, X dice per group, Y die size, with an optional modifier.
    """

    die: int = 32
    enable_hat_rolls: bool = True
    enable_generic_rolls: bool = False


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
    hat: HatConfig
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


def _coerce_guild_id(value: Any, ctx: str) -> int:
    if value is None or value == "":
        raise ConfigError(f"{ctx} must be a non-empty Discord guild ID")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{ctx} must be an integer") from exc


def _parse_guild_ids(discord_raw: dict[str, Any]) -> tuple[int, ...]:
    """Read ``guild_ids`` (list) plus the legacy ``guild_id`` (single).

    Both are optional; either or both may be present. Duplicates are
    removed while preserving the order they first appear in the file.
    """
    ordered: list[int] = []
    seen: set[int] = set()

    def _add(value: int) -> None:
        if value not in seen:
            ordered.append(value)
            seen.add(value)

    legacy = discord_raw.get("guild_id")
    if legacy not in (None, ""):
        _add(_coerce_guild_id(legacy, "config.discord.guild_id"))

    raw_list = discord_raw.get("guild_ids")
    if raw_list is None:
        return tuple(ordered)
    if not isinstance(raw_list, list):
        raise ConfigError("config.discord.guild_ids must be a list of integers")
    for index, item in enumerate(raw_list):
        _add(_coerce_guild_id(item, f"config.discord.guild_ids[{index}]"))
    return tuple(ordered)


def _coerce_bool(value: Any, ctx: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    raise ConfigError(f"{ctx} must be a boolean")


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
    guild_ids = _parse_guild_ids(discord_raw)
    discord = DiscordConfig(
        username=discord_raw.get("username"),
        avatar_url=discord_raw.get("avatar_url"),
        bot_token=discord_raw.get("bot_token") or None,
        guild_ids=guild_ids,
    )

    hat_raw = raw.get("hat", {}) or {}
    try:
        die = int(hat_raw.get("die", HatConfig().die))
    except (TypeError, ValueError) as exc:
        raise ConfigError("config.hat.die must be an integer") from exc
    if die < 2:
        raise ConfigError("config.hat.die must be >= 2")
    enable_hat_rolls = _coerce_bool(
        hat_raw.get("enable_hat_rolls", HatConfig().enable_hat_rolls),
        "config.hat.enable_hat_rolls",
    )
    enable_generic_rolls = _coerce_bool(
        hat_raw.get("enable_generic_rolls", HatConfig().enable_generic_rolls),
        "config.hat.enable_generic_rolls",
    )
    hat = HatConfig(
        die=die,
        enable_hat_rolls=enable_hat_rolls,
        enable_generic_rolls=enable_generic_rolls,
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
        hat=hat,
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
        discord=DiscordConfig(username="Skill Tracker (demo)", guild_ids=()),
        hat=HatConfig(die=32, enable_hat_rolls=True, enable_generic_rolls=True),
        sheet_template=template,
        players=players,
        source_path=DEMO_SOURCE,
    )


def is_demo_config(config: AppConfig) -> bool:
    return config.source_path == DEMO_SOURCE
