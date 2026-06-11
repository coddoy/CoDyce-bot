"""``/hat`` dice-rolling command.

Parses the textual command, rolls the dice, and formats a Discord-ready
reply. The functions here are deliberately UI-agnostic so the same code
powers both the Tk demo entry box *and* the Discord slash-command
handler.

Two independent parsers feed the same command, gated by config flags
(:class:`app.config.HatConfig`):

* **Hat shorthand** (``enable_hat_rolls``) — the game-system specific
  form that rolls ``1d{config.die}+modifier`` and uses the ``hit``
  keyword for d100::

      <modifier>            # 1 d{die} + modifier
      <count> <modifier>    # count groups of 1 d{die} + modifier
      hit                   # 1 d100   (X defaults to 1)
      <count> hit           # count d100   (X must be < 10)
      <count>hit            # count d100   (X must be < 10, sticky)
      hit <count>           # count d100   (X must be < 10)
      hit<count>            # count d100   (X must be < 10, sticky)

* **Generic** (``enable_generic_rolls``) — the universal
  ``Z XdY[+/-#]`` form::

      dY                    # 1 group of 1 dY
      XdY                   # 1 group of X dY
      Z XdY                 # Z groups of X dY
      Z XdY +N | -N         # …with a per-group modifier
      …[reason text]        # free-form reason captured verbatim

  Z defaults to 1, X defaults to 1. Limits: ``Z <= 20``,
  ``X <= 1000``, ``Y <= 1000``, ``|modifier| <= 1000``. Modifier
  options may be tight (``3d6+2``) or spaced (``3d6 + 2``).

Output form depends on group count:

* **One group** (Z == 1) → single-line message with the dice listed
  inline, identical in shape to the original ``/hat`` reply.
* **Multiple groups** (Z > 1) → first-line summary plus one
  ``Set N: …`` line per group.

Any text after the matched dice expression is captured as the roll's
*reason* and echoed back in the formatted reply.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

HIT_KEYWORD = "hit"
HIT_DIE = 100
HIT_MAX_COUNT = 9  # "Xhit" / "X hit" / "hitX" / "hit X" require X < 10
HELP_KEYWORD = "help"

MAX_GROUPS = 20      # Z
MAX_DIE_COUNT = 1000  # X
MAX_DIE_SIZE = 1000   # Y
MAX_MODIFIER = 1000   # |+/-#|


class HatCommandError(ValueError):
    """Raised when the user's input cannot be parsed as a /hat command."""


@dataclass(frozen=True)
class RollGroup:
    """One ``XdY+/-#`` group within a roll request."""

    count: int      # X — number of dice rolled in this group
    die: int        # Y — sides per die
    modifier: int   # added to the group's sum

    def __post_init__(self) -> None:
        if self.count < 1:
            raise HatCommandError("Roll count (X) must be at least 1.")
        if self.count > MAX_DIE_COUNT:
            raise HatCommandError(
                f"Roll count (X) must be at most {MAX_DIE_COUNT}."
            )
        if self.die < 2:
            raise HatCommandError("Die size (Y) must be at least 2.")
        if self.die > MAX_DIE_SIZE:
            raise HatCommandError(
                f"Die size (Y) must be at most {MAX_DIE_SIZE}."
            )
        if abs(self.modifier) > MAX_MODIFIER:
            raise HatCommandError(
                f"Modifier must be between -{MAX_MODIFIER} and +{MAX_MODIFIER}."
            )


@dataclass(frozen=True)
class HatRequest:
    """A parsed roll request — Z groups of identical XdY+/-# dice.

    All groups in a single request share their X/Y/modifier; only the
    count of groups (Z) varies between hat shorthand and generic
    forms.
    """

    groups: tuple[RollGroup, ...]
    is_hit: bool = False
    reason: str = ""

    def __post_init__(self) -> None:
        if not self.groups:
            raise HatCommandError("At least one roll group is required.")
        if len(self.groups) > MAX_GROUPS:
            raise HatCommandError(
                f"Number of groups (Z) must be at most {MAX_GROUPS}."
            )

    @property
    def num_groups(self) -> int:
        return len(self.groups)


@dataclass(frozen=True)
class HatResult:
    """The dice rolled for a :class:`HatRequest`.

    ``group_rolls[i]`` is the tuple of dice rolled for group ``i``.
    """

    request: HatRequest
    group_rolls: tuple[tuple[int, ...], ...] = field(default_factory=tuple)

    def total_for(self, group_index: int) -> int:
        rolls = self.group_rolls[group_index]
        modifier = self.request.groups[group_index].modifier
        return sum(rolls) + modifier


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
# Generic form: optional Z, required XdY (X may be empty), optional
# +/- modifier (with optional whitespace around the sign), optional
# trailing reason. ``re.DOTALL`` lets reasons that contain newlines
# survive intact, although we already strip incoming text.
_GENERIC_RE = re.compile(
    r"""
    ^
    (?:(?P<z>\d+)\s+)?              # optional Z, requires trailing space
    (?P<x>\d*)d(?P<y>\d+)           # XdY (X defaults to 1 when empty)
    (?:\s*(?P<sign>[+-])\s*(?P<mag>\d+))?  # optional +/- modifier
    (?:\s+(?P<reason>.*))?          # optional reason, must be space-separated
    $
    """,
    re.VERBOSE | re.IGNORECASE | re.DOTALL,
)

_STICKY_HIT_BEFORE_RE = re.compile(r"^(\d+)hit$", re.IGNORECASE)
_STICKY_HIT_AFTER_RE = re.compile(r"^hit(\d+)$", re.IGNORECASE)


def _strip_hat_prefix(text: str) -> str:
    """Drop a leading ``/hat`` or ``hat`` prefix from command text."""
    cleaned = text.strip()
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    if lowered.startswith("/hat"):
        return cleaned[len("/hat"):].strip()
    if lowered.startswith("hat "):
        return cleaned[len("hat"):].strip()
    return cleaned


def _matches_keyword(token: str, keyword: str) -> bool:
    """Return whether ``token`` equals ``keyword``."""
    return token.lower() == keyword.lower()


def _first_token(text: str) -> str | None:
    cleaned = _strip_hat_prefix(text)
    if not cleaned:
        return None
    return cleaned.split(None, 1)[0].lower()


def is_help_command(text: str | None) -> bool:
    """Return True when ``text`` is a ``/hat help`` invocation.

    Accepts the bare argument (``help``), a leading-slash form
    (``/hat help``), or the no-slash equivalent (``hat help``). Trailing
    tokens are ignored so ``help me`` / ``/hat help rolls`` also count.
    """
    if not text:
        return False
    return _first_token(text) == HELP_KEYWORD


def format_hat_help(
    hat_die: int,
    *,
    enable_hat: bool,
    enable_generic: bool,
) -> str:
    """Render the user-visible ``/hat help`` reply.

    The body is gated by which parsers are enabled in config so users
    only see examples that will actually work.
    """
    lines: list[str] = ["**`/hat` command — dice rolling**", ""]

    if enable_hat:
        lines.append(f"__Hat shorthand__ (rolls `1d{hat_die}` plus a modifier):")
        lines.append(f"\u2022 `/hat 52` \u2192 1d{hat_die}+52")
        lines.append(
            f"\u2022 `/hat 3 33` \u2192 3 sets of 1d{hat_die}+33"
        )
        lines.append("\u2022 `/hat hit` \u2192 1d100")
        lines.append(
            "\u2022 `/hat 3 hit` or `/hat 3hit` \u2192 3 sets of 1d100"
        )
        lines.append(
            "\u2022 `/hat hit 3` or `/hat hit3` \u2192 3 sets of 1d100"
        )
        lines.append("")

    if enable_generic:
        lines.append("__Generic dice__ (`Z XdY[+/-#]`):")
        lines.append("\u2022 `/hat d20` \u2192 1d20")
        lines.append("\u2022 `/hat 3d6+2` \u2192 3d6+2")
        lines.append("\u2022 `/hat 2 4d8` \u2192 2 sets of 4d8")
        lines.append("\u2022 `/hat 3 d10+1` \u2192 3 sets of 1d10+1")
        lines.append(
            f"Limits: Z\u2264{MAX_GROUPS}, X\u2264{MAX_DIE_COUNT}, "
            f"Y\u2264{MAX_DIE_SIZE}, |modifier|\u2264{MAX_MODIFIER}."
        )
        lines.append("")

    if not enable_hat and not enable_generic:
        lines.append(
            "_All roll parsers are currently disabled in config._"
        )
        lines.append("")

    lines.append(
        "Any extra words after the dice are kept as a *reason* and "
        "echoed back in the reply (e.g. `/hat 3d6 fire damage`)."
    )
    lines.append("Use `/hat help` to see this message again.")
    return "\n".join(lines).rstrip()


def _try_int(token: str | None) -> int | None:
    if token is None:
        return None
    try:
        return int(token)
    except ValueError:
        return None


def parse_hat_command(
    text: str,
    hat_die: int,
    *,
    enable_hat: bool = True,
    enable_generic: bool = False,
) -> HatRequest:
    """Parse a raw ``/hat`` command string into a :class:`HatRequest`.

    The two parser families are tried in this order: generic first
    (the ``d`` token disambiguates it from hat shorthand), then hat
    shorthand. If both are disabled, every input is rejected.
    """
    if text is None:
        raise HatCommandError("No command provided.")

    cleaned = _strip_hat_prefix(text)
    if not cleaned:
        raise HatCommandError(_empty_help(enable_hat, enable_generic))

    if not enable_hat and not enable_generic:
        raise HatCommandError(
            "Both hat rolls and generic rolls are disabled in config."
        )

    if enable_generic:
        match = _GENERIC_RE.match(cleaned)
        if match:
            return _build_generic_request(match)

    if enable_hat:
        return _parse_hat_form(cleaned, hat_die)

    raise HatCommandError(
        "Could not parse roll. Generic format requires `XdY[+/-#]` "
        "(e.g., `3d6+2`); hat shorthand is disabled in config."
    )


def _empty_help(enable_hat: bool, enable_generic: bool) -> str:
    examples: list[str] = []
    if enable_hat:
        examples.extend(["`52`", "`3 33`", "`hit`"])
    if enable_generic:
        examples.extend(["`d20`", "`3d6+2`", "`2 4d8`"])
    if not examples:
        return "Both hat and generic rolls are disabled in config."
    return f"Empty command. Try {', '.join(examples)}."


def _build_groups(group: RollGroup, count: int) -> tuple[RollGroup, ...]:
    """Build a tuple of ``count`` identical groups, validating size first.

    The ``HatRequest.__post_init__`` size check fires *after* its
    ``groups`` argument is materialized, so we must reject oversized
    counts here to avoid allocating a multi-billion-entry tuple from
    user input like ``/hat 999999999999 d6``.
    """
    if count < 1:
        raise HatCommandError("At least one roll group is required.")
    if count > MAX_GROUPS:
        raise HatCommandError(
            f"Number of groups (Z) must be at most {MAX_GROUPS}."
        )
    return tuple(group for _ in range(count))


def _build_generic_request(match: "re.Match[str]") -> HatRequest:
    z_raw = match.group("z")
    x_raw = match.group("x")
    y_raw = match.group("y")
    sign = match.group("sign")
    mag_raw = match.group("mag")
    reason_raw = match.group("reason")

    z = int(z_raw) if z_raw else 1
    x = int(x_raw) if x_raw else 1
    y = int(y_raw)
    modifier = 0
    if sign and mag_raw:
        magnitude = int(mag_raw)
        modifier = magnitude if sign == "+" else -magnitude
    reason = (reason_raw or "").strip()

    group = RollGroup(count=x, die=y, modifier=modifier)
    return HatRequest(
        groups=_build_groups(group, z),
        is_hit=False,
        reason=reason,
    )


def _parse_hat_form(cleaned: str, hat_die: int) -> HatRequest:
    tokens = cleaned.split()
    if not tokens:
        raise HatCommandError("Missing arguments.")

    first = tokens[0]

    # "Xhit" sticky form (X must be 1..9)
    sticky_before = _STICKY_HIT_BEFORE_RE.match(first)
    if sticky_before:
        count = int(sticky_before.group(1))
        if 1 <= count <= HIT_MAX_COUNT:
            return _build_hit_request(count, tokens[1:])
        # Out-of-range sticky hit: fall through to other parsers; if
        # nothing else matches the user gets a useful error below.

    # "hitX" sticky form (X must be 1..9)
    sticky_after = _STICKY_HIT_AFTER_RE.match(first)
    if sticky_after:
        count = int(sticky_after.group(1))
        if 1 <= count <= HIT_MAX_COUNT:
            return _build_hit_request(count, tokens[1:])

    # Bare "hit" possibly followed by a small count
    if _matches_keyword(first, HIT_KEYWORD):
        count = 1
        rest = tokens[1:]
        if rest:
            n = _try_int(rest[0])
            if n is not None and 1 <= n <= HIT_MAX_COUNT:
                count = n
                rest = rest[1:]
        return _build_hit_request(count, rest)

    first_int = _try_int(first)
    if first_int is None:
        raise HatCommandError(
            f"Could not understand `{first}`. "
            "Start with an integer (e.g., `52`, `3 33`, `hit`)."
        )

    second = tokens[1] if len(tokens) >= 2 else None

    # "X hit" (X must be 1..9)
    if (
        second is not None
        and _matches_keyword(second, HIT_KEYWORD)
        and 1 <= first_int <= HIT_MAX_COUNT
    ):
        return _build_hit_request(first_int, tokens[2:])

    second_int = _try_int(second) if second is not None else None
    if second_int is not None:
        # "X N" → X groups of 1d{hat_die}+N
        reason = " ".join(tokens[2:]).strip()
        group = RollGroup(count=1, die=hat_die, modifier=second_int)
        return HatRequest(
            groups=_build_groups(group, first_int),
            is_hit=False,
            reason=reason,
        )

    # "N" — single hat roll with N as the modifier; trailing tokens are reason.
    reason = " ".join(tokens[1:]).strip()
    group = RollGroup(count=1, die=hat_die, modifier=first_int)
    return HatRequest(groups=(group,), is_hit=False, reason=reason)


def _build_hit_request(count: int, rest_tokens: list[str]) -> HatRequest:
    reason = " ".join(rest_tokens).strip()
    group = RollGroup(count=1, die=HIT_DIE, modifier=0)
    return HatRequest(
        groups=_build_groups(group, count),
        is_hit=True,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Rolling
# ---------------------------------------------------------------------------
def roll_hat(request: HatRequest, rng: random.Random | None = None) -> HatResult:
    """Roll the dice described by ``request``."""
    r = rng or random
    group_rolls = tuple(
        tuple(r.randint(1, group.die) for _ in range(group.count))
        for group in request.groups
    )
    return HatResult(request=request, group_rolls=group_rolls)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
def _format_modifier(modifier: int) -> str:
    if modifier > 0:
        return f"+{modifier}"
    if modifier < 0:
        return str(modifier)
    return ""


def _format_group_expr(group: RollGroup, *, leading_one: bool) -> str:
    """Render a group as ``XdY+/-#``.

    ``leading_one=True`` prints ``1d{Y}`` for X==1 (matches the
    original single-roll hat output). ``leading_one=False`` drops the
    leading 1 so it reads ``d{Y}`` (matches the original multi-roll
    hat header).
    """
    mod = _format_modifier(group.modifier)
    if group.count > 1:
        return f"{group.count}d{group.die}{mod}"
    if leading_one:
        return f"1d{group.die}{mod}"
    return f"d{group.die}{mod}"


def format_hat_message(player: str, result: HatResult) -> str:
    """Render the player-visible reply for a completed roll."""
    req = result.request
    reason_str = f" Reason: {req.reason}" if req.reason else ""

    if req.num_groups == 1:
        group = req.groups[0]
        formula = _format_group_expr(group, leading_one=True)
        rolls = result.group_rolls[0]
        rolls_str = ", ".join(str(r) for r in rolls)
        total = result.total_for(0)
        return (
            f"\U0001F3B2 {player} Request: {formula}{reason_str} "
            f"Roll: [{rolls_str}] = {total}"
        )

    # Multi-group form. All groups share their X/Y/modifier, so the
    # header reads "{Z} <inner>".
    inner = _format_group_expr(req.groups[0], leading_one=False)
    formula = f"{req.num_groups} {inner}"
    lines = [f"\U0001F3B2 {player} Request: {formula}{reason_str}"]
    for index, rolls in enumerate(result.group_rolls, start=1):
        rolls_str = ", ".join(str(r) for r in rolls)
        total = result.total_for(index - 1)
        lines.append(f"Set {index}: Roll: [{rolls_str}] = {total}")
    return "\n".join(lines)


__all__ = [
    "HatCommandError",
    "HatRequest",
    "HatResult",
    "RollGroup",
    "format_hat_help",
    "format_hat_message",
    "is_help_command",
    "parse_hat_command",
    "roll_hat",
]
