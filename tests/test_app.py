"""HTTP contract tests for the UI and error states."""

import re
from hashlib import sha256

from fastapi.testclient import TestClient
from test_service import Backend

from ticker_lens.app import app
from ticker_lens.providers import Settings


def test_given_missing_config_when_analyzing_then_returns_explicit_error(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)

    with TestClient(app) as client:
        result = client.post("/api/analyze", json={"ticker": "MSFT"})

    assert result.status_code == 503
    assert "FINNHUB_API_KEY" in result.json()["detail"]


def test_given_no_news_when_calling_api_then_returns_zero_tally_and_rubric():
    backend = Backend([])
    backend.settings = Settings(finnhub_api_key="test", azure_endpoint="https://test.example.com")
    with TestClient(app) as client:
        app.state.providers = backend

        result = client.post("/api/analyze", json={"ticker": " msft "})

    assert result.status_code == 200
    data = result.json()
    assert data["ticker"] == "MSFT"
    assert data["rows"] == []
    assert data["scanned"] == data["available"] == data["neutral_skipped"] == 0
    assert data["scan_timed_out"] is False
    assert sum(data["tally"].values()) == 0
    assert data["lean"] == {
        "bullish_weight": 0.0,
        "bearish_weight": 0.0,
        "score": None,
        "label": "No directional signal",
    }
    assert len(data["questions"]) == 3


def test_given_invalid_ticker_when_calling_api_then_rejects_before_external_calls():
    with TestClient(app) as client:
        result = client.post("/api/analyze", json={"ticker": "../../bad"})

    assert result.status_code == 422


def test_given_app_when_loading_then_serves_ui_and_health():
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        page = client.get("/")
        assert page.status_code == 200
        assert "Ticker Lens" in page.text
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]


def test_given_cached_assets_when_loading_home_then_page_revalidates_and_uses_versioned_urls():
    # Arrange
    with TestClient(app) as client:
        # Act
        page = client.get("/")
        assets = re.findall(r'(?:href|src)="(/static/[^"]+)"', page.text)

        # Assert
        assert page.headers.get("cache-control") == "no-cache"
        assert len(assets) == 2
        for url in assets:
            asset = client.get(url)
            assert asset.status_code == 200
            assert url.endswith(f"?v={sha256(asset.content).hexdigest()[:16]}")
