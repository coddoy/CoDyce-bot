"""Google Sheets read/write wrapper.

Authentication uses a Google Cloud service account JSON file (see
README for setup). The service account email **must** be shared on
each player's spreadsheet as an Editor.

Caching strategy: when a player's sheet is loaded for the first time
we issue one ``batch_get`` covering every skill cell in the template.
After that, increments only round-trip the single cell being changed
and the local cache is updated in place. Use
:meth:`SheetsClient.invalidate` (or pass ``force=True`` to
``load_player_skills``) to drop the cache and refetch.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .config import AppConfig, PlayerConfig, SheetTemplate

if TYPE_CHECKING:  # pragma: no cover - typing only
    import gspread

log = logging.getLogger(__name__)


class SheetsError(RuntimeError):
    """Raised on any Google Sheets failure surfaced to the UI."""


@dataclass
class _PlayerCache:
    spreadsheet: "gspread.Spreadsheet"
    worksheet: "gspread.Worksheet"
    values: dict[str, int]


class SheetsClient:
    """Lazy wrapper around :mod:`gspread`.

    The client is constructed cheaply; the underlying gspread client
    is only created on first use, so the UI can boot even when the
    credentials file is missing — the user just gets a friendly error
    when they try to load a sheet.
    """

    def __init__(self, app_config: AppConfig) -> None:
        self._cfg = app_config
        self._gc: "gspread.Client" | None = None
        self._cache: dict[str, _PlayerCache] = {}

    # ------------------------------------------------------------------
    # auth
    # ------------------------------------------------------------------
    def _client(self) -> "gspread.Client":
        if self._gc is not None:
            return self._gc
        try:
            import gspread
            from gspread.http_client import BackOffHTTPClient
        except ImportError as exc:
            raise SheetsError(
                "gspread is not installed. Run: pip install -r requirements.txt"
            ) from exc

        creds_path = Path(self._cfg.google.credentials_file)
        if not creds_path.exists():
            raise SheetsError(
                f"Google credentials file not found: {creds_path}. "
                "See README.md for service-account setup steps."
            )

        try:
            self._gc = gspread.service_account(
                filename=str(creds_path),
                http_client=BackOffHTTPClient,
            )
        except Exception as exc:  # noqa: BLE001 - surface any auth failure
            raise SheetsError(f"Failed to authenticate with Google: {exc}") from exc
        return self._gc

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def load_player_skills(
        self, player: PlayerConfig, *, force: bool = False
    ) -> dict[str, int]:
        """Return ``{skill_name: value}`` for the given player.

        Values are read in a single batch and cached. Pass ``force=True``
        to bypass the cache and refetch from Sheets.
        """
        if not force and player.name in self._cache:
            return dict(self._cache[player.name].values)

        template = self._cfg.sheet_template
        gc = self._client()

        try:
            spreadsheet = gc.open_by_key(player.spreadsheet_id)
            worksheet = spreadsheet.worksheet(player.worksheet_name(template))
        except Exception as exc:  # noqa: BLE001
            raise SheetsError(
                f"Could not open spreadsheet for {player.name}: {exc}"
            ) from exc

        ranges = [template.cell_for(s) for s in template.skill_names]
        try:
            results = worksheet.batch_get(ranges)
        except Exception as exc:  # noqa: BLE001
            raise SheetsError(
                f"Failed to read skills for {player.name}: {exc}"
            ) from exc

        values: dict[str, int] = {}
        for skill, raw in zip(template.skill_names, results):
            values[skill] = _parse_int_cell(raw)

        self._cache[player.name] = _PlayerCache(
            spreadsheet=spreadsheet, worksheet=worksheet, values=values
        )
        return dict(values)

    def increment_skill(
        self, player: PlayerConfig, skill: str, delta: int
    ) -> tuple[int, int]:
        """Apply ``delta`` to the player's skill cell.

        Returns ``(old_value, new_value)``. Updates the local cache.
        """
        if player.name not in self._cache:
            self.load_player_skills(player)

        cache = self._cache[player.name]
        template = self._cfg.sheet_template
        cell = template.cell_for(skill)

        old_value = cache.values.get(skill, 0)
        new_value = old_value + int(delta)

        try:
            cache.worksheet.update_acell(cell, new_value)
        except Exception as exc:  # noqa: BLE001
            raise SheetsError(
                f"Failed to update {skill} ({cell}) for {player.name}: {exc}"
            ) from exc

        cache.values[skill] = new_value
        return old_value, new_value

    def invalidate(self, player_name: str | None = None) -> None:
        """Drop cached values for one player (or all when ``None``)."""
        if player_name is None:
            self._cache.clear()
        else:
            self._cache.pop(player_name, None)


def _parse_int_cell(raw: object) -> int:
    """Best-effort conversion of a ``batch_get`` cell to ``int``.

    ``batch_get`` returns ``[[value]]`` for a single-cell range, or
    ``[]`` if the cell is empty. We treat empty/non-numeric as ``0``
    so the UI can still display and increment.
    """
    if not raw:
        return 0
    try:
        cell = raw[0][0]  # type: ignore[index]
    except (IndexError, TypeError):
        return 0
    if cell is None or cell == "":
        return 0
    try:
        return int(float(str(cell).replace(",", "")))
    except ValueError:
        log.warning("Non-numeric skill cell value %r treated as 0", cell)
        return 0


# Stand-in for tests / offline UI work without the gspread dependency.
class FakeSheetsClient:
    """In-memory implementation that mimics :class:`SheetsClient`.

    Useful for running the UI without configuring Google credentials.
    Every player starts with all skills at zero (or values supplied
    via the ``seed`` constructor argument).
    """

    def __init__(
        self,
        app_config: AppConfig,
        seed: dict[str, dict[str, int]] | None = None,
    ) -> None:
        self._cfg = app_config
        seed = seed or {}
        self._values: dict[str, dict[str, int]] = {
            name: {
                skill: seed.get(name, {}).get(skill, 0)
                for skill in app_config.sheet_template.skill_names
            }
            for name in app_config.player_names
        }

    def load_player_skills(
        self, player: PlayerConfig, *, force: bool = False  # noqa: ARG002
    ) -> dict[str, int]:
        return dict(self._values[player.name])

    def increment_skill(
        self, player: PlayerConfig, skill: str, delta: int
    ) -> tuple[int, int]:
        old = self._values[player.name].get(skill, 0)
        new = old + int(delta)
        self._values[player.name][skill] = new
        return old, new

    def invalidate(self, player_name: str | None = None) -> None:  # noqa: ARG002
        return None
