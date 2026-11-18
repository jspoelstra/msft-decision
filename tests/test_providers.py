"""Verify exact outbound API shapes and safe errors with stubbed transports."""

import json
from datetime import date

import httpx
import pytest
from azure.core.credentials import AccessToken
from test_decision import response

from ticker_lens.providers import ProviderError, Providers, Settings


class Credential:
    async def get_token(self, scope):
        assert scope == "https://cognitiveservices.azure.com/.default"
        return AccessToken("test-token", 9999999999)


async def test_given_article_when_scoring_then_posts_one_typed_request_to_resource():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=response())

    settings = Settings(
        finnhub_api_key="not-real",
        azure_endpoint="https://test.services.ai.azure.com",
        deployment_name="my-deployment",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        backend = Providers(settings, client, Credential())

        result = await backend.decide({"ticker": "MSFT", "headline": "Example", "summary": ""})

    assert result.answers["outlook"].choice == "Bullish"
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://test.services.ai.azure.com/providers/microsoft/v1/systemone"
    body = json.loads(request.content)
    assert body["model"] == "my-deployment"
    assert set(body["questions"]) == {"outlook", "impact", "evidence"}
    assert set(body["questions"]["outlook"]["criteria"]) == {
        "Bullish", "Bearish", "Neutral or mixed"
    }
    assert request.headers["authorization"] == "Bearer test-token"


async def test_given_provider_error_when_fetching_then_hides_credentials():
    settings = Settings(finnhub_api_key="never-echo-this")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(403))
    ) as client:
        backend = Providers(settings, client, Credential())

        with pytest.raises(ProviderError, match="^Finnhub returned HTTP 403.$"):
            await backend.news("MSFT", date(2026, 11, 11), date(2026, 11, 17))
