"""``/hat`` dice-rolling command.

Parses the textual command, rolls the dice, and formats a Discord-ready
reply. The functions here are deliberately UI-agnostic so the same code
powers both the Tk demo entry box *and* a future Discord slash-command
handler.

Supported syntax (case-insensitive, leading ``/hat`` optional)::

    <modifier>            # 1 d{config.die} + modifier
    <count> <modifier>    # count d{config.die} + modifier
    hit                   # 1 d100
    <count> hit           # count d100
    <count>hit            # count d100  (sticky form)

Any trailing text after the matched prefix is captured verbatim as the
roll's *reason* and echoed back in the formatted reply, e.g.::

    /hat 52 attack with sword     -> 1d32+52, reason "attack with sword"
    /hat 3 33 burst fire          -> 3 d32+33, reason "burst fire"
    /hat 3 hit aoe                -> 3 d100,   reason "aoe"

Examples (with ``config.hat.die == 32``)::

    /hat 52        -> 1d32+52
    /hat 3 33      -> 3 d32+33  (three sets of 1d32+33 each)
    /hat hit       -> 1d100
    /hat 3 hit     -> 3 d100
    /hat 3hit      -> 3 d100
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

HIT_KEYWORD = "hit"
HIT_DIE = 100

MAX_COUNT = 100  # keep replies under Discord's 2000-char ceiling


class HatCommandError(ValueError):
    """Raised when the user's input cannot be parsed as a /hat command."""


@dataclass(frozen=True)
class HatRequest:
    count: int
    die: int
    modifier: int
    is_hit: bool = False
    reason: str = ""

    def __post_init__(self) -> None:
        if self.count < 1:
            raise HatCommandError("Roll count must be at least 1.")
        if self.count > MAX_COUNT:
            raise HatCommandError(
                f"Roll count must be at most {MAX_COUNT}."
            )
        if self.die < 2:
            raise HatCommandError("Die size must be at least 2.")


@dataclass(frozen=True)
class HatResult:
    request: HatRequest
    rolls: tuple[int, ...] = field(default_factory=tuple)

    @property
    def totals(self) -> tuple[int, ...]:
        return tuple(roll + self.request.modifier for roll in self.rolls)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
_STICKY_HIT_RE = re.compile(r"^(\d+)hit$", re.IGNORECASE)


def _try_int(token: str) -> int | None:
    try:
        return int(token)
    except ValueError:
        return None


def parse_hat_command(text: str, default_die: int) -> HatRequest:
    """Parse a raw ``/hat`` command string into a :class:`HatRequest`.

    Accepts an optional leading ``/hat`` (or ``hat``) prefix so users
    can paste either form into the demo entry box.

    The matched prefix is consumed greedily (numbers and/or the ``hit``
    keyword); any tokens left over are joined into
    :attr:`HatRequest.reason` so callers can render a free-form note
    alongside the roll.
    """
    if text is None:
        raise HatCommandError("No command provided.")

    cleaned = text.strip()
    if not cleaned:
        raise HatCommandError(
            "Empty command. Try `/hat 52`, `/hat 3 33`, or `/hat hit`."
        )

    lowered = cleaned.lower()
    if lowered.startswith("/hat"):
        cleaned = cleaned[len("/hat"):].strip()
    elif lowered.startswith("hat "):
        cleaned = cleaned[len("hat"):].strip()

    if not cleaned:
        raise HatCommandError(
            "Missing arguments. Try `52`, `3 33`, `hit`, or `3 hit`."
        )

    tokens = cleaned.split()
    first = tokens[0]

    # Greedy prefix match — pick the longest pattern the leading tokens
    # satisfy, then everything else falls through to the reason.
    sticky = _STICKY_HIT_RE.match(first)
    if sticky:
        consumed = 1
        request_kwargs: dict = {
            "count": int(sticky.group(1)),
            "die": HIT_DIE,
            "modifier": 0,
            "is_hit": True,
        }
    elif first.lower() == HIT_KEYWORD:
        consumed = 1
        request_kwargs = {
            "count": 1,
            "die": HIT_DIE,
            "modifier": 0,
            "is_hit": True,
        }
    else:
        first_int = _try_int(first)
        if first_int is None:
            raise HatCommandError(
                f"Could not understand `{first}`. "
                "Start with an integer (and optionally `hit`)."
            )

        second = tokens[1] if len(tokens) >= 2 else None
        second_int = _try_int(second) if second is not None else None

        if second is not None and second.lower() == HIT_KEYWORD:
            consumed = 2
            request_kwargs = {
                "count": first_int,
                "die": HIT_DIE,
                "modifier": 0,
                "is_hit": True,
            }
        elif second_int is not None:
            consumed = 2
            request_kwargs = {
                "count": first_int,
                "die": default_die,
                "modifier": second_int,
            }
        else:
            consumed = 1
            request_kwargs = {
                "count": 1,
                "die": default_die,
                "modifier": first_int,
            }

    reason = " ".join(tokens[consumed:]).strip()
    return HatRequest(reason=reason, **request_kwargs)


# ---------------------------------------------------------------------------
# Rolling
# ---------------------------------------------------------------------------
def roll_hat(request: HatRequest, rng: random.Random | None = None) -> HatResult:
    """Roll the dice described by ``request``."""
    r = rng or random
    rolls = tuple(r.randint(1, request.die) for _ in range(request.count))
    return HatResult(request=request, rolls=rolls)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------
def _format_modifier(modifier: int) -> str:
    if modifier > 0:
        return f"+{modifier}"
    if modifier < 0:
        return str(modifier)  # already includes minus sign
    return ""


def format_hat_message(player: str, result: HatResult) -> str:
    """Render the player-visible reply for a completed roll."""
    req = result.request
    mod_str = _format_modifier(req.modifier)
    reason_str = f" Reason: {req.reason}" if req.reason else ""

    if req.count == 1:
        formula = f"1d{req.die}{mod_str}"
        roll = result.rolls[0]
        total = roll + req.modifier
        return (
            f"\U0001F3B2 {player} Request: {formula}{reason_str} "
            f"Roll: [{roll}] = {total}"
        )

    # Multi-roll form: matches the spec'd "<count> d<die><mod>" with a
    # single space between the count and the die expression.
    formula = f"{req.count} d{req.die}{mod_str}"
    lines = [f"\U0001F3B2 {player} Request: {formula}{reason_str}"]
    for index, roll in enumerate(result.rolls, start=1):
        total = roll + req.modifier
        lines.append(f"Set {index}: Roll: [{roll}] = {total}")
    return "\n".join(lines)


__all__ = [
    "HatCommandError",
    "HatRequest",
    "HatResult",
    "format_hat_message",
    "parse_hat_command",
    "roll_hat",
]
