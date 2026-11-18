"""Analysis tests without live news, Azure credentials, or a browser."""

import asyncio
from datetime import UTC, date, datetime

import pytest
from pydantic import HttpUrl
from test_decision import response

from ticker_lens.decision import validate_decisions
from ticker_lens.providers import Article, ProviderError
from ticker_lens.service import analyze, normalize_ticker, select_articles

TODAY = date(2026, 11, 17)
TIMESTAMP = int(datetime(2026, 11, 17, tzinfo=UTC).timestamp())


def article(identifier, url=None, timestamp=TIMESTAMP):
    return Article(
        id=identifier,
        headline=f"Story {identifier}",
        summary="",
        source="Test wire",
        datetime=timestamp,
        url=HttpUrl(url or f"https://example.com/{identifier}"),
    )


@pytest.mark.parametrize("value", ["", "../secrets", "ABC&token=secret", "A" * 50])
def test_given_invalid_ticker_when_normalizing_then_rejects(value):
    with pytest.raises(ValueError):
        normalize_ticker(value)


def test_given_duplicates_and_old_news_when_selecting_then_keeps_all_unique_recent_candidates():
    stories = [
        article(1),
        article(1, "https://example.com/duplicate"),
        article(2, "https://example.com/1"),
        article(3, timestamp=1),
    ]
    stories += [article(i) for i in range(4, 20)]

    selected = select_articles(stories, date(2026, 11, 11), TODAY)

    assert len(selected) == 17
    assert [item.id for item in selected[:2]] == [1, 4]


class Backend:
    def __init__(self, stories):
        self.stories = stories
        self.active = 0
        self.max_active = 0
        self.calls = 0
        self.news_calls = []

    async def news(self, ticker, start, end):
        self.news_calls.append((start, end))
        return self.stories

    async def decide(self, state):
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0)
        self.active -= 1
        if state["headline"] == "Story 1":
            raise ProviderError("Foundry returned HTTP 429.")
        return validate_decisions(response())


async def test_given_one_model_failure_when_analyzing_then_retains_article_and_limits_work():
    backend = Backend([article(i) for i in range(1, 11)])

    result = await analyze(" msft ", backend, TODAY)

    assert result.ticker == "MSFT"
    assert result.rows[0].bucket == "Unscored"
    assert result.rows[0].error == "Foundry returned HTTP 429."
    assert result.rows[0].article.id == 1
    assert sum(result.tally.values()) == 10
    assert result.lean.bullish_weight == pytest.approx(9 * 0.8 * 13 / 15)
    assert backend.calls == 10
    assert backend.max_active <= 3


async def test_given_no_news_when_analyzing_then_makes_no_model_calls():
    backend = Backend([])

    result = await analyze("MSFT", backend, TODAY)

    assert result.rows == []
    assert backend.calls == 0


@pytest.mark.parametrize("matches", [0, 4, 15])
async def test_given_neutral_prefix_when_scanning_then_finds_ten_or_exhausts_window(matches):
    # Arrange
    class MixedBackend(Backend):
        async def decide(self, state):
            self.calls += 1
            identifier = int(state["headline"].split()[-1])
            return validate_decisions(
                response("Neutral or mixed" if identifier <= 12 else
                         "Bullish" if identifier % 2 else "Bearish")
            )

    stories = [article(i, timestamp=TIMESTAMP - i) for i in range(1, 13 + matches)]
    backend = MixedBackend(list(reversed(stories)))

    # Act
    result = await analyze("MSFT", backend, TODAY)

    # Assert
    expected = min(matches, 10)
    assert [row.article.id for row in result.rows] == list(range(13, 13 + expected))
    assert result.scanned == backend.calls == 12 + expected
    assert result.available == 12 + matches
    assert result.neutral_skipped == 12
    assert result.tally["Neutral or mixed"] == 0
    assert sum(result.tally.values()) == expected
    assert result.scan_timed_out is False


async def test_given_scoring_failure_when_scanning_then_continues_until_ten_matches():
    backend = Backend([article(i) for i in range(1, 20)])

    result = await analyze("MSFT", backend, TODAY)

    assert backend.calls == result.scanned == 11
    assert result.tally["Bullish"] == 10
    assert result.tally["Unscored"] == 1
    assert result.rows[0].error == "Foundry returned HTTP 429."


async def test_given_scan_timeout_when_analyzing_then_returns_explicit_partial_results(monkeypatch):
    class SlowBackend(Backend):
        async def decide(self, state):
            if state["headline"] == "Story 5":
                await asyncio.sleep(3600)
            return validate_decisions(response())

    monkeypatch.setattr("ticker_lens.service.SCAN_TIMEOUT_SECONDS", 0.02)
    backend = SlowBackend([article(i) for i in range(2, 10)])

    result = await analyze("MSFT", backend, TODAY)

    assert result.scan_timed_out is True
    assert result.scanned == 3
    assert result.available == 8
    assert len(result.rows) == 3


async def test_given_ten_matches_today_when_scanning_then_does_not_fetch_older_days():
    backend = Backend([article(i) for i in range(2, 20)])

    result = await analyze("MSFT", backend, TODAY)

    assert backend.news_calls == [(TODAY, TODAY)]
    assert result.days_fetched == 1
    assert result.tally["Bullish"] == 10


async def test_given_empty_days_when_scanning_then_respects_configured_lookback():
    backend = Backend([])

    result = await analyze("MSFT", backend, TODAY, lookback_days=2)

    assert backend.news_calls == [
        (TODAY, TODAY), (date(2026, 11, 16), date(2026, 11, 16))
    ]
    assert result.start == date(2026, 11, 16)
    assert result.days_fetched == result.lookback_days == 2
    assert backend.calls == 0


async def test_given_multiple_days_when_scanning_then_preserves_order_and_deduplicates():
    backend = Backend([
        article(2),
        article(3, timestamp=TIMESTAMP - 86400),
        article(4, url="https://example.com/2", timestamp=TIMESTAMP - 86400),
        article(2, timestamp=TIMESTAMP - 86400),
        article(5, timestamp=TIMESTAMP - 2 * 86400),
    ])

    result = await analyze("MSFT", backend, TODAY, lookback_days=2)

    assert [row.article.id for row in result.rows] == [2, 3]
    assert result.scanned == result.available == backend.calls == 2
    assert len(backend.news_calls) == 2


async def test_given_later_news_failure_when_scanning_then_returns_explicit_partial_results():
    class FailingNewsBackend(Backend):
        async def news(self, ticker, start, end):
            if start != TODAY:
                raise ProviderError("Finnhub returned HTTP 429.")
            return self.stories

    result = await analyze("MSFT", FailingNewsBackend([article(2)]), TODAY)

    assert len(result.rows) == 1
    assert result.days_fetched == 1
    assert result.scan_error == "Finnhub returned HTTP 429."
