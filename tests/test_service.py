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


def test_given_duplicate_urls_ids_and_old_news_when_selecting_then_bounds_results():
    stories = [
        article(1),
        article(1, "https://example.com/duplicate"),
        article(2, "https://example.com/1"),
        article(3, timestamp=1),
    ]
    stories += [article(i) for i in range(4, 20)]

    selected = select_articles(stories, date(2026, 11, 11), TODAY)

    assert len(selected) == 10
    assert [item.id for item in selected[:2]] == [1, 4]


class Backend:
    def __init__(self, stories):
        self.stories = stories
        self.active = 0
        self.max_active = 0
        self.calls = 0

    async def news(self, ticker, start, end):
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
    assert backend.calls == 10
    assert backend.max_active <= 3


async def test_given_no_news_when_analyzing_then_makes_no_model_calls():
    backend = Backend([])

    result = await analyze("MSFT", backend, TODAY)

    assert result.rows == []
    assert backend.calls == 0
