"""Focused tests of the rubric policy and malformed model output."""

import copy

import pytest
from pydantic import ValidationError

from ticker_lens.decision import (
    QUESTIONS,
    DecisionError,
    news_lean,
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
        ("Bullish", 0.699, "Bullish"),
        ("Bearish", 0.4, "Bearish"),
        ("Neutral or mixed", 0.4, "Neutral or mixed"),
    ],
)
def test_given_outlook_when_classifying_then_keeps_selected_label_at_any_confidence(
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


def test_given_errors_when_tallying_then_does_not_count_as_neutral():
    result = tally(["Bullish", "Unscored"])

    assert result == {
        "Bullish": 1,
        "Bearish": 0,
        "Neutral or mixed": 0,
        "Unscored": 1,
    }


def test_given_low_confidence_stories_when_weighting_then_impact_can_reverse_the_lean():
    # Arrange
    outlooks = [
        ("Bullish", [0.6, 0.1, 0.3], [0, 0, 1, 0]),
        ("Bearish", [0.2, 0.6, 0.2], [0.5, 0.5, 0, 0]),
    ]
    decisions = []
    for choice, outlook, impact in outlooks:
        payload = response(choice)
        payload["answers"]["outlook"]["probabilities"] = dict(
            zip(QUESTIONS["outlook"].criteria, outlook, strict=True)
        )
        payload["answers"]["impact"]["probabilities"] = dict(
            zip(QUESTIONS["impact"].criteria, impact, strict=True)
        )
        decisions.append(validate_decisions(payload))

    # Act
    result = news_lean(decisions)

    # Assert
    assert [outlook_bucket(decision) for decision in decisions] == ["Bullish", "Bearish"]
    assert result.bullish_weight == pytest.approx(11 / 30)
    assert result.bearish_weight == pytest.approx(8 / 15)
    assert (result.score, result.label) == (-14, "Leaning bearish")


@pytest.mark.parametrize(
    ("bullish", "bearish", "impact", "score", "label"),
    [
        (0.50, 0.45, "High", 5, "Balanced"),
        (0.50, 0.44, "High", 6, "Leaning bullish"),
        (0.44, 0.50, "High", -6, "Leaning bearish"),
        (0.8, 0.1, "Cannot tell", None, "No directional signal"),
        (0, 0, "High", None, "No directional signal"),
    ],
)
def test_given_directional_weights_when_summarizing_then_reports_lean_or_no_signal(
    bullish, bearish, impact, score, label
):
    # Arrange
    payload = response()
    payload["answers"]["outlook"] = {
        "type": "choice",
        "choice": "Bullish" if bullish else "Neutral or mixed",
        "probabilities": {
            "Bullish": bullish,
            "Bearish": bearish,
            "Neutral or mixed": 1 - (bullish + bearish),
        },
    }
    payload["answers"]["impact"]["probabilities"] = {
        name: int(name == impact) for name in QUESTIONS["impact"].criteria
    }

    # Act
    result = news_lean([validate_decisions(payload)])

    # Assert
    assert (result.score, result.label) == (score, label)
