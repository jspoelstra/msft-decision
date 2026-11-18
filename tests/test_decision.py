"""Focused tests of the rubric policy and malformed model output."""

import copy

import pytest
from pydantic import ValidationError

from ticker_lens.decision import (
    QUESTIONS,
    DecisionError,
    outlook_bucket,
    tally,
    validate_decisions,
)


def response(outlook="Bullish", probability=0.8):
    answers = {}
    for name, question in QUESTIONS.items():
        options = list(question.criteria)
        choice = outlook if name == "outlook" else options[0]
        probabilities = {
            option: probability if option == choice else (1 - probability) / (len(options) - 1)
            for option in options
        }
        answers[name] = {"type": "choice", "choice": choice, "probabilities": probabilities}
    return {"model": "microsoft-decision-1.1", "answers": answers}


@pytest.mark.parametrize(
    ("choice", "probability", "expected"),
    [
        ("Bullish", 0.70, "Bullish"),
        ("Bearish", 0.8, "Bearish"),
        ("Neutral or mixed", 0.8, "Neutral or mixed"),
        ("Bullish", 0.699, "Needs review"),
        ("Not enough context", 0.99, "Needs review"),
    ],
)
def test_given_outlook_when_applying_threshold_then_preserves_abstention(
    choice, probability, expected
):
    decisions = validate_decisions(response(choice, probability))

    assert outlook_bucket(decisions) == expected


@pytest.mark.parametrize("defect", ["missing", "unknown", "nan", "total"])
def test_given_malformed_response_when_validating_then_fails_explicitly(defect):
    payload = copy.deepcopy(response())
    answer = payload["answers"]["outlook"]
    if defect == "missing":
        del payload["answers"]["evidence"]
    elif defect == "unknown":
        answer["choice"] = "Buy now"
    elif defect == "nan":
        answer["probabilities"]["Bullish"] = float("nan")
    else:
        answer["probabilities"]["Bullish"] = 0.2

    with pytest.raises((DecisionError, ValidationError)):
        validate_decisions(payload)


def test_given_review_and_errors_when_tallying_then_neither_counts_as_neutral():
    result = tally(["Bullish", "Needs review", "Unscored"])

    assert result == {
        "Bullish": 1,
        "Bearish": 0,
        "Neutral or mixed": 0,
        "Needs review": 1,
        "Unscored": 1,
    }
