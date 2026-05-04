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


def parse_hat_command(text: str, default_die: int) -> HatRequest:
    """Parse a raw ``/hat`` command string into a :class:`HatRequest`.

    Accepts an optional leading ``/hat`` (or ``hat``) prefix so users
    can paste either form into the demo entry box.
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

    raw_parts = cleaned.split()

    # Expand sticky "Nhit" into ["N", "hit"] so the rest of the parser
    # only ever sees space-separated tokens.
    parts: list[str] = []
    for token in raw_parts:
        match = _STICKY_HIT_RE.match(token)
        if match:
            parts.append(match.group(1))
            parts.append(HIT_KEYWORD)
        else:
            parts.append(token)

    is_hit = any(p.lower() == HIT_KEYWORD for p in parts)
    nums_raw = [p for p in parts if p.lower() != HIT_KEYWORD]

    nums: list[int] = []
    for token in nums_raw:
        try:
            nums.append(int(token))
        except ValueError as exc:
            raise HatCommandError(
                f"Could not understand `{token}`. "
                "Use integers (and optionally `hit`)."
            ) from exc

    if is_hit:
        if len(nums) > 1:
            raise HatCommandError(
                "`hit` rolls accept at most one number (the count)."
            )
        count = nums[0] if nums else 1
        return HatRequest(count=count, die=HIT_DIE, modifier=0, is_hit=True)

    if len(nums) == 1:
        return HatRequest(count=1, die=default_die, modifier=nums[0])
    if len(nums) == 2:
        return HatRequest(count=nums[0], die=default_die, modifier=nums[1])

    raise HatCommandError(
        "Expected `<modifier>`, `<count> <modifier>`, or a `hit` form."
    )


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

    if req.count == 1:
        formula = f"1d{req.die}{mod_str}"
        roll = result.rolls[0]
        total = roll + req.modifier
        return f"\U0001F3B2 {player} Request: {formula} Roll: [{roll}] = {total}"

    # Multi-roll form: matches the spec'd "<count> d<die><mod>" with a
    # single space between the count and the die expression.
    formula = f"{req.count} d{req.die}{mod_str}"
    lines = [f"\U0001F3B2 {player} Request: {formula}"]
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
