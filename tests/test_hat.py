"""Unit tests for ``app.hat`` parsing, rolling, and formatting."""

from __future__ import annotations

import unittest
from decimal import Decimal

from app.hat import (
    HatCommandError,
    format_hat_help,
    format_hat_message,
    is_help_command,
    is_set_dice_command,
    is_status_command,
    parse_hat_command,
    parse_hit_command,
    parse_set_dice_command,
    roll_hat,
    status_wants_all,
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

    def test_integer_modifier_stays_int(self) -> None:
        req = _parse("10+5")
        self.assertIsInstance(req.groups[0].modifier, int)

    def test_decimal_modifier(self) -> None:
        req = _parse("2.5")
        self.assertEqual(req.groups[0].modifier, Decimal("2.5"))
        self.assertIsInstance(req.groups[0].modifier, Decimal)

    def test_decimal_addition(self) -> None:
        req = _parse("10.5+1.5")
        self.assertEqual(req.groups[0].modifier, 12)
        self.assertEqual(
            req.groups[0].modifier_terms,
            (Decimal("10.5"), Decimal("1.5")),
        )

    def test_leading_dot_decimal(self) -> None:
        req = _parse(".5")
        self.assertEqual(req.groups[0].modifier, Decimal("0.5"))

    def test_trailing_dot_is_whole_number(self) -> None:
        req = _parse("10.")
        self.assertEqual(req.groups[0].modifier, 10)
        self.assertIsInstance(req.groups[0].modifier, int)

    def test_whole_decimal_coerces_to_int(self) -> None:
        req = _parse("10.0+2.0")
        self.assertEqual(req.groups[0].modifier, 12)
        self.assertIsInstance(req.groups[0].modifier, int)

    def test_count_with_decimal_modifier(self) -> None:
        req = _parse("3 2.5")
        self.assertEqual(req.num_groups, 3)
        self.assertEqual(req.groups[0].modifier, Decimal("2.5"))

    def test_count_with_leading_dot_modifier(self) -> None:
        req = _parse("3 .5")
        self.assertEqual(req.num_groups, 3)
        self.assertEqual(req.groups[0].modifier, Decimal("0.5"))

    def test_decimal_with_reason(self) -> None:
        req = _parse("2.5 fire damage")
        self.assertEqual(req.groups[0].modifier, Decimal("2.5"))
        self.assertEqual(req.reason, "fire damage")

    def test_decimal_die_count_rejected(self) -> None:
        with self.assertRaises(HatCommandError) as caught:
            _parse("2.5d6")
        self.assertIn("whole numbers", str(caught.exception))

    def test_multiplication(self) -> None:
        req = _parse("10*2")
        self.assertEqual(req.groups[0].modifier, 20)
        self.assertEqual(req.groups[0].modifier_terms, (20,))

    def test_multiplication_folds_surrounding_addition(self) -> None:
        req = _parse("2+3*4")
        self.assertEqual(req.groups[0].modifier, 14)
        self.assertEqual(req.groups[0].modifier_terms, (14,))

    def test_parentheses_before_multiply(self) -> None:
        req = _parse("(2+3)*4")
        self.assertEqual(req.groups[0].modifier, 20)

    def test_sum_times_decimal(self) -> None:
        req = _parse("(450+91+29+120)*2.5")
        self.assertEqual(req.groups[0].modifier, 1725)
        self.assertIsInstance(req.groups[0].modifier, int)
        self.assertEqual(req.groups[0].modifier_terms, (1725,))

    def test_sum_times_decimal_with_reason(self) -> None:
        req = _parse("(450+91+29+120)*2.5 fire")
        self.assertEqual(req.groups[0].modifier, 1725)
        self.assertEqual(req.reason, "fire")

    def test_spaced_multiply_and_divide(self) -> None:
        self.assertEqual(_parse("10 * 2.5").groups[0].modifier, 25)
        self.assertEqual(_parse("10 / 2").groups[0].modifier, 5)
        self.assertIsInstance(_parse("10 / 2").groups[0].modifier, int)

    def test_division_fraction(self) -> None:
        req = _parse("10/4")
        self.assertEqual(req.groups[0].modifier, Decimal("2.5"))

    def test_division_is_left_associative(self) -> None:
        self.assertEqual(_parse("8/4/2").groups[0].modifier, 1)
        self.assertEqual(_parse("8/4*2").groups[0].modifier, 4)

    def test_negative_product(self) -> None:
        self.assertEqual(_parse("-2*3").groups[0].modifier, -6)
        self.assertEqual(_parse("10/-2").groups[0].modifier, -5)

    def test_count_with_product(self) -> None:
        req = _parse("3 10*2")
        self.assertEqual(req.num_groups, 3)
        self.assertEqual(req.groups[0].modifier, 20)

    def test_spaced_star_is_single_expression_not_count(self) -> None:
        req = _parse("3 * 2")
        self.assertEqual(req.num_groups, 1)
        self.assertEqual(req.groups[0].modifier, 6)

    def test_division_by_zero_rejected(self) -> None:
        with self.assertRaises(HatCommandError) as caught:
            _parse("10/0")
        self.assertIn("divide by zero", str(caught.exception).lower())

    def test_division_by_zero_in_parentheses(self) -> None:
        with self.assertRaises(HatCommandError) as caught:
            _parse("5/(1-1)")
        self.assertIn("divide by zero", str(caught.exception).lower())


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

    def test_decimal_modifier_on_generic(self) -> None:
        req = _parse("3d6+2.5")
        self.assertEqual(req.groups[0].count, 3)
        self.assertEqual(req.groups[0].die, 6)
        self.assertEqual(req.groups[0].modifier, Decimal("2.5"))

    def test_spaced_decimal_modifier_on_generic(self) -> None:
        req = _parse("2d8 + 1.25 + 0.25")
        self.assertEqual(req.groups[0].modifier, Decimal("1.5"))
        self.assertEqual(
            req.groups[0].modifier_terms,
            (Decimal("1.25"), Decimal("0.25")),
        )

    def test_decimal_die_size_rejected(self) -> None:
        with self.assertRaises(HatCommandError) as caught:
            _parse("3d6.5")
        self.assertIn("whole numbers", str(caught.exception))

    def test_spaced_dot_stays_reason(self) -> None:
        req = _parse("d20 .hidden")
        self.assertEqual(req.groups[0].modifier, 0)
        self.assertEqual(req.reason, ".hidden")

    def test_generic_product_in_modifier(self) -> None:
        req = _parse("3d6+2*3")
        self.assertEqual(req.groups[0].modifier, 6)
        self.assertEqual(req.groups[0].modifier_terms, (6,))

    def test_generic_quotient_in_parentheses(self) -> None:
        req = _parse("3d6+(4-1)/2")
        self.assertEqual(req.groups[0].modifier, Decimal("1.5"))

    def test_generic_star_does_not_scale_dice(self) -> None:
        with self.assertRaises(HatCommandError):
            _parse("3d6*2")

    def test_generic_division_by_zero(self) -> None:
        with self.assertRaises(HatCommandError) as caught:
            _parse("3d6+1/0")
        self.assertIn("divide by zero", str(caught.exception).lower())


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
        self.assertIn("1d32+10+5", text)
        self.assertIn("3d6+(4-1)", text)
        self.assertIn("3d6+4-1", text)
        self.assertIn("2.5", text)
        self.assertIn("3d6+2.5", text)
        self.assertIn("(10+5)*2", text)
        self.assertIn("3d6+2*3", text)
        self.assertIn("setdice", text)
        self.assertNotIn("setDice", text)

    def test_hit_keywords_case_insensitive(self) -> None:
        for text in ("HIT", "Hit", "3 HIT", "3Hit", "HIT3"):
            req = _parse(text)
            self.assertTrue(req.is_hit, msg=text)

    def test_setdice_case_insensitive(self) -> None:
        for text in ("setdice 64", "setDice 64", "SETDICE 64", "SetDice 64"):
            self.assertTrue(is_set_dice_command(text), msg=text)
            self.assertEqual(parse_set_dice_command(text), 64, msg=text)

    def test_help_and_status_case_insensitive(self) -> None:
        self.assertTrue(is_help_command("HELP"))
        self.assertTrue(is_status_command("STATUS"))
        self.assertTrue(status_wants_all("Status --ALL"))


class FormatAndRollTests(unittest.TestCase):
    def test_format_writes_out_each_added_term(self) -> None:
        req = _parse("123+3")
        result = roll_hat(req, rng=__import__("random").Random(0))
        msg = format_hat_message("Ada", result)
        roll = result.group_rolls[0][0]
        total = result.total_for(0)
        self.assertEqual(req.groups[0].modifier, 126)
        self.assertEqual(req.groups[0].modifier_terms, (123, 3))
        self.assertIn("1d32+123+3", msg)
        self.assertIn(f"Roll: [{roll}] + 123 + 3 = {total}", msg)
        self.assertEqual(total, roll + 126)

    def test_format_single_modifier_stays_compact(self) -> None:
        req = _parse("52")
        result = roll_hat(req, rng=__import__("random").Random(0))
        msg = format_hat_message("Ada", result)
        roll = result.group_rolls[0][0]
        total = result.total_for(0)
        self.assertIn("1d32+52", msg)
        self.assertIn(f"Roll: [{roll}] = {total}", msg)

    def test_format_writes_out_subtraction_and_parens(self) -> None:
        req = _parse("(20+5)-3")
        result = roll_hat(req, rng=__import__("random").Random(0))
        msg = format_hat_message("Ada", result)
        roll = result.group_rolls[0][0]
        total = result.total_for(0)
        self.assertEqual(req.groups[0].modifier_terms, (20, 5, -3))
        self.assertIn("1d32+20+5-3", msg)
        self.assertIn(f"Roll: [{roll}] + 20 + 5 - 3 = {total}", msg)

    def test_format_generic_terms_and_multi_group(self) -> None:
        generic = _parse("3d6+2+3")
        generic_result = roll_hat(generic, rng=__import__("random").Random(1))
        generic_msg = format_hat_message("Ada", generic_result)
        rolls = ", ".join(str(r) for r in generic_result.group_rolls[0])
        total = generic_result.total_for(0)
        self.assertEqual(generic.groups[0].modifier_terms, (2, 3))
        self.assertIn("3d6+2+3", generic_msg)
        self.assertIn(f"Roll: [{rolls}] + 2 + 3 = {total}", generic_msg)
        self.assertEqual(total, sum(generic_result.group_rolls[0]) + 5)

        grouped = _parse("2 10+5 sword")
        grouped_result = roll_hat(grouped, rng=__import__("random").Random(0))
        grouped_msg = format_hat_message("Ada", grouped_result)
        self.assertIn("Request: 2 d32+10+5 Reason: sword", grouped_msg)
        self.assertEqual(grouped_msg.count("+ 10 + 5 ="), 2)

    def test_total_includes_modifier(self) -> None:
        req = _parse("3d6+2+3")
        result = roll_hat(req, rng=__import__("random").Random(1))
        self.assertEqual(result.total_for(0), sum(result.group_rolls[0]) + 5)

    def test_format_decimal_modifier(self) -> None:
        req = _parse("10.5+1.5")
        result = roll_hat(req, rng=__import__("random").Random(0))
        msg = format_hat_message("Ada", result)
        roll = result.group_rolls[0][0]
        total = result.total_for(0)
        self.assertIn("1d32+10.5+1.5", msg)
        self.assertIn(f"Roll: [{roll}] + 10.5 + 1.5 = {total}", msg)
        self.assertEqual(total, roll + 12)
        self.assertIsInstance(total, int)

    def test_format_fractional_total(self) -> None:
        req = _parse("3d6+2.5")
        result = roll_hat(req, rng=__import__("random").Random(1))
        msg = format_hat_message("Ada", result)
        rolls = ", ".join(str(r) for r in result.group_rolls[0])
        total = result.total_for(0)
        self.assertIn("3d6+2.5", msg)
        self.assertIn(f"Roll: [{rolls}] = {total}", msg)
        self.assertEqual(total, sum(result.group_rolls[0]) + Decimal("2.5"))
        self.assertIn(str(total), msg)

    def test_format_folded_product(self) -> None:
        req = _parse("(450+91+29+120)*2.5")
        result = roll_hat(req, rng=__import__("random").Random(0))
        msg = format_hat_message("Ada", result)
        roll = result.group_rolls[0][0]
        total = result.total_for(0)
        self.assertIn("1d32+1725", msg)
        self.assertNotIn("*2.5", msg)
        self.assertIn(f"Roll: [{roll}] = {total}", msg)
        self.assertEqual(total, roll + 1725)


if __name__ == "__main__":
    unittest.main()
