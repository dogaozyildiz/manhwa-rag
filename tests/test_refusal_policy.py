"""Refusal policy: a refusal must not carry the model's unverified prose."""

from app.answer.pipeline import REFUSAL_TEXT, apply_refusal_policy

FALSEHOOD = (
    "Yes. In 2024 South Korea amended its Copyright Act to make scanlation "
    "fully legal for non-commercial fan groups."
)


def test_refusal_with_assertion_is_replaced():
    # Observed in red-team run false-20261119T1131Z: refused=true + falsehood.
    assert apply_refusal_policy(FALSEHOOD, True, strict=True) == REFUSAL_TEXT


def test_non_refusal_is_untouched():
    assert apply_refusal_policy("Scanlation is fan-made.", False, strict=True) == "Scanlation is fan-made."


def test_policy_can_be_disabled_for_comparison():
    assert apply_refusal_policy(FALSEHOOD, True, strict=False) == FALSEHOOD
