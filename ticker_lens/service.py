"""Analysis orchestration with bounded work and explicit partial failures."""

import asyncio
import logging
import re
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from pydantic import BaseModel

from ticker_lens.decision import Bucket, Decisions, NewsLean, news_lean, outlook_bucket, tally
from ticker_lens.providers import Article, ProviderError

logger = logging.getLogger(__name__)
SCAN_TIMEOUT_SECONDS = 180


class Backend(Protocol):
    async def news(self, ticker: str, start: date, end: date) -> list[Article]: ...
    async def decide(self, state: dict[str, str]) -> Decisions: ...


class Row(BaseModel):
    article: Article
    input_depth: str
    state: dict[str, str]
    bucket: Bucket
    decisions: Decisions | None = None
    error: str | None = None


class Analysis(BaseModel):
    ticker: str
    start: date
    end: date
    rows: list[Row]
    tally: dict[Bucket, int]
    lean: NewsLean
    scanned: int
    available: int
    neutral_skipped: int
    scan_timed_out: bool


def normalize_ticker(ticker: str) -> str:
    normalized = ticker.strip().upper()
    if not re.fullmatch(r"[A-Z]{1,5}(?:[.-][A-Z]{1,2})?", normalized):
        raise ValueError("Enter a U.S. ticker such as MSFT, AAPL, or BRK.B.")
    return normalized


def select_articles(articles: list[Article], start: date, end: date) -> list[Article]:
    selected: list[Article] = []
    seen_ids: set[int] = set()
    seen_urls: set[str] = set()
    for article in sorted(articles, key=lambda item: item.datetime, reverse=True):
        published = datetime.fromtimestamp(article.datetime, UTC).date()
        if not start <= published <= end:
            continue
        url = str(article.url)
        if article.id in seen_ids or url in seen_urls:
            continue
        seen_ids.add(article.id)
        seen_urls.add(url)
        selected.append(article)
    return selected


async def analyze(ticker: str, backend: Backend, today: date | None = None) -> Analysis:
    ticker = normalize_ticker(ticker)
    end = today or datetime.now(UTC).date()
    start = end - timedelta(days=6)
    articles = select_articles(await backend.news(ticker, start, end), start, end)

    async def score(article: Article) -> Row:
        state = {"ticker": ticker, "headline": article.headline, "summary": article.summary}
        row = Row(
            article=article,
            state=state,
            input_depth="Headline and summary" if article.summary.strip() else "Headline only",
            bucket="Unscored",
        )
        try:
            row.decisions = await backend.decide(state)
            row.bucket = outlook_bucket(row.decisions)
        except ProviderError as exc:
            logger.warning("Article %s could not be scored: %s", article.id, exc)
            row.error = str(exc)
        return row

    rows: list[Row] = []
    directional = scanned = neutral_skipped = 0
    scan_timed_out = False
    try:
        async with asyncio.timeout(SCAN_TIMEOUT_SECONDS):
            while scanned < len(articles) and directional < 10:
                # Never start more calls than the remaining match slots.
                batch = articles[scanned : scanned + min(3, 10 - directional)]
                scored = await asyncio.gather(*(score(article) for article in batch))
                scanned += len(scored)
                for row in scored:
                    if row.bucket == "Neutral or mixed":
                        neutral_skipped += 1
                    else:
                        rows.append(row)
                        if row.bucket in ("Bullish", "Bearish"):
                            directional += 1
    except TimeoutError:
        scan_timed_out = True
        logger.warning("News scan timed out after %s completed articles", scanned)

    return Analysis(
        ticker=ticker,
        start=start,
        end=end,
        rows=rows,
        tally=tally([row.bucket for row in rows]),
        lean=news_lean(row.decisions for row in rows if row.decisions is not None),
        scanned=scanned,
        available=len(articles),
        neutral_skipped=neutral_skipped,
        scan_timed_out=scan_timed_out,
    )
