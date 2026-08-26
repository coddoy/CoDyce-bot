"""Unit tests for ``app.hat`` parsing, rolling, and formatting."""

from __future__ import annotations

import unittest

from app.hat import (
    HatCommandError,
    format_hat_help,
    format_hat_message,
    parse_hat_command,
    parse_hit_command,
    roll_hat,
)


HAT_DIE = 32


def _parse(text: str, *, enable_hat: bool = True, enable_generic: bool = True):
    return parse_hat_command(
        text,
        HAT_DIE,
        enable_hat=enable_hat,
        enable_generic=enable_generic,
    )


class HatShorthandTests(unittest.TestCase):
    def test_single_modifier(self) -> None:
        req = _parse("52")
        self.assertEqual(req.num_groups, 1)
        self.assertEqual(req.groups[0].die, HAT_DIE)
        self.assertEqual(req.groups[0].modifier, 52)
        self.assertEqual(req.reason, "")

    def test_count_and_modifier(self) -> None:
        req = _parse("3 33")
        self.assertEqual(req.num_groups, 3)
        self.assertEqual(req.groups[0].modifier, 33)

    def test_modifier_addition_tight(self) -> None:
        req = _parse("10+5")
        self.assertEqual(req.num_groups, 1)
        self.assertEqual(req.groups[0].modifier, 15)

    def test_modifier_addition_spaced(self) -> None:
        req = _parse("10 + 5")
        self.assertEqual(req.groups[0].modifier, 15)

    def test_modifier_subtraction_and_parens(self) -> None:
        req = _parse("(20+5)-3")
        self.assertEqual(req.groups[0].modifier, 22)

    def test_modifier_spaced_parens(self) -> None:
        req = _parse(" ( 2 + 3 ) + 1 ")
        self.assertEqual(req.groups[0].modifier, 6)

    def test_count_with_modifier_math(self) -> None:
        req = _parse("3 10+5")
        self.assertEqual(req.num_groups, 3)
        self.assertEqual(req.groups[0].modifier, 15)

    def test_count_with_spaced_modifier_math(self) -> None:
        req = _parse("3 10 + 5")
        self.assertEqual(req.num_groups, 3)
        self.assertEqual(req.groups[0].modifier, 15)

    def test_count_with_paren_modifier(self) -> None:
        req = _parse("2 (4+1)")
        self.assertEqual(req.num_groups, 2)
        self.assertEqual(req.groups[0].modifier, 5)

    def test_count_with_stuck_negative_modifier(self) -> None:
        req = _parse("3 -5")
        self.assertEqual(req.num_groups, 3)
        self.assertEqual(req.groups[0].modifier, -5)

    def test_spaced_plus_is_single_expression_not_count(self) -> None:
        # ``3 + 5`` is math (8), not ``3`` groups of ``+5``.
        req = _parse("3 + 5")
        self.assertEqual(req.num_groups, 1)
        self.assertEqual(req.groups[0].modifier, 8)

    def test_reason_after_modifier_math(self) -> None:
        req = _parse("10+5 fire damage")
        self.assertEqual(req.groups[0].modifier, 15)
        self.assertEqual(req.reason, "fire damage")

    def test_reason_after_spaced_modifier_math(self) -> None:
        req = _parse("10 + 5 sword")
        self.assertEqual(req.groups[0].modifier, 15)
        self.assertEqual(req.reason, "sword")

    def test_reason_after_count_and_math(self) -> None:
        req = _parse("3 10 + 5 heavy hit")
        self.assertEqual(req.num_groups, 3)
        self.assertEqual(req.groups[0].modifier, 15)
        self.assertEqual(req.reason, "heavy hit")

    def test_reason_after_plain_modifier(self) -> None:
        req = _parse("52 because reasons")
        self.assertEqual(req.groups[0].modifier, 52)
        self.assertEqual(req.reason, "because reasons")

    def test_negative_modifier_expression(self) -> None:
        req = _parse("-3+10")
        self.assertEqual(req.groups[0].modifier, 7)

    def test_incomplete_modifier_math_rejected(self) -> None:
        with self.assertRaises(HatCommandError):
            _parse("10+")

    def test_incomplete_count_modifier_math_rejected(self) -> None:
        with self.assertRaises(HatCommandError):
            _parse("3 10+")

    def test_unbalanced_parens_rejected(self) -> None:
        with self.assertRaises(HatCommandError):
            _parse("(1+2")

    def test_reason_requires_space(self) -> None:
        with self.assertRaises(HatCommandError):
            _parse("10+5fire")


class GenericModifierTests(unittest.TestCase):
    def test_simple_modifier(self) -> None:
        req = _parse("3d6+2")
        self.assertEqual(req.num_groups, 1)
        self.assertEqual(req.groups[0].count, 3)
        self.assertEqual(req.groups[0].die, 6)
        self.assertEqual(req.groups[0].modifier, 2)

    def test_spaced_modifier(self) -> None:
        req = _parse("3d6 + 2")
        self.assertEqual(req.groups[0].modifier, 2)

    def test_modifier_math(self) -> None:
        req = _parse("3d6+2+3")
        self.assertEqual(req.groups[0].modifier, 5)

    def test_modifier_math_spaced(self) -> None:
        req = _parse("3d6 + 1 + 2")
        self.assertEqual(req.groups[0].modifier, 3)

    def test_modifier_parens(self) -> None:
        req = _parse("3d6+(4-1)")
        self.assertEqual(req.groups[0].modifier, 3)

    def test_modifier_parens_spaced(self) -> None:
        req = _parse("2d8 + (2 - 1)")
        self.assertEqual(req.groups[0].modifier, 1)

    def test_reason_after_modifier_math(self) -> None:
        req = _parse("3d6 + 2 + 3 fire damage")
        self.assertEqual(req.groups[0].modifier, 5)
        self.assertEqual(req.reason, "fire damage")

    def test_reason_without_modifier(self) -> None:
        req = _parse("d20 insight")
        self.assertEqual(req.groups[0].modifier, 0)
        self.assertEqual(req.reason, "insight")

    def test_multi_group_with_math(self) -> None:
        req = _parse("2 4d8+1+1")
        self.assertEqual(req.num_groups, 2)
        self.assertEqual(req.groups[0].count, 4)
        self.assertEqual(req.groups[0].die, 8)
        self.assertEqual(req.groups[0].modifier, 2)

    def test_incomplete_generic_modifier_rejected(self) -> None:
        with self.assertRaises(HatCommandError):
            _parse("3d6+")


class HitAndHelpTests(unittest.TestCase):
    def test_hit_unchanged(self) -> None:
        req = _parse("hit")
        self.assertTrue(req.is_hit)
        self.assertEqual(req.num_groups, 1)
        self.assertEqual(req.groups[0].die, 100)

    def test_count_hit(self) -> None:
        req = _parse("3 hit")
        self.assertTrue(req.is_hit)
        self.assertEqual(req.num_groups, 3)

    def test_hit_command_parser(self) -> None:
        req = parse_hit_command("3")
        self.assertTrue(req.is_hit)
        self.assertEqual(req.num_groups, 3)

    def test_help_mentions_modifier_math(self) -> None:
        text = format_hat_help(HAT_DIE, enable_hat=True, enable_generic=True)
        self.assertIn("10+5", text)
        self.assertIn("3d6+(4-1)", text)


class FormatAndRollTests(unittest.TestCase):
    def test_format_uses_evaluated_modifier(self) -> None:
        req = _parse("10+5")
        result = roll_hat(req, rng=__import__("random").Random(0))
        msg = format_hat_message("Ada", result)
        self.assertIn("1d32+15", msg)

    def test_total_includes_modifier(self) -> None:
        req = _parse("3d6+2+3")
        result = roll_hat(req, rng=__import__("random").Random(1))
        self.assertEqual(result.total_for(0), sum(result.group_rolls[0]) + 5)


if __name__ == "__main__":
    unittest.main()
