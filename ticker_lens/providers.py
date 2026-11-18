"""Finnhub retrieval and keyless Azure Foundry inference adapters."""

import os
from datetime import date

import httpx
from azure.core.exceptions import AzureError
from azure.identity.aio import DefaultAzureCredential
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError

from ticker_lens.decision import DecisionError, Decisions, questions_payload, validate_decisions


class ProviderError(RuntimeError):
    """An external service failed without exposing credentials."""


class Settings(BaseModel):
    finnhub_api_key: str = ""
    azure_endpoint: str = ""
    deployment_name: str = "decision"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            finnhub_api_key=os.getenv("FINNHUB_API_KEY", ""),
            azure_endpoint=os.getenv("AZURE_ENDPOINT", "").rstrip("/"),
            deployment_name=os.getenv("DEPLOYMENT_NAME", "decision"),
        )

    def require_configured(self) -> None:
        missing = [
            name
            for name, value in (
                ("FINNHUB_API_KEY", self.finnhub_api_key),
                ("AZURE_ENDPOINT", self.azure_endpoint),
                ("DEPLOYMENT_NAME", self.deployment_name),
            )
            if not value
        ]
        if missing:
            raise ProviderError("Missing server configuration: " + ", ".join(missing))
        if not self.azure_endpoint.startswith("https://"):
            raise ProviderError("AZURE_ENDPOINT must be an HTTPS Foundry resource endpoint.")


class Article(BaseModel):
    id: int
    headline: str = Field(min_length=1, max_length=4000)
    summary: str = Field(default="", max_length=20000)
    source: str
    datetime: int = Field(ge=0, le=253402300799)
    url: HttpUrl

    model_config = ConfigDict(extra="ignore")


class Providers:
    def __init__(
        self, settings: Settings, client: httpx.AsyncClient, credential: DefaultAzureCredential
    ) -> None:
        self.settings = settings
        self.client = client
        self.credential = credential

    async def news(self, ticker: str, start: date, end: date) -> list[Article]:
        try:
            response = await self.client.get(
                "https://finnhub.io/api/v1/company-news",
                params={"symbol": ticker, "from": start.isoformat(), "to": end.isoformat()},
                headers={"X-Finnhub-Token": self.settings.finnhub_api_key},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, list):
                raise ProviderError("Finnhub did not return a news list. Check your API access.")
            return [Article.model_validate(item) for item in payload]
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Finnhub returned HTTP {exc.response.status_code}.") from None
        except httpx.RequestError:
            raise ProviderError(
                "Finnhub could not be reached within the request timeout."
            ) from None
        except (ValueError, ValidationError):
            raise ProviderError("Finnhub returned malformed news data.") from None

    async def decide(self, state: dict[str, str]) -> Decisions:
        try:
            token = await self.credential.get_token("https://cognitiveservices.azure.com/.default")
            response = await self.client.post(
                self.settings.azure_endpoint + "/providers/microsoft/v1/systemone",
                headers={"Authorization": f"Bearer {token.token}"},
                json={
                    "model": self.settings.deployment_name,
                    "state": state,
                    "questions": questions_payload(),
                },
                timeout=45,
            )
            response.raise_for_status()
            return validate_decisions(response.json())
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Foundry returned HTTP {exc.response.status_code}.") from None
        except httpx.RequestError:
            raise ProviderError(
                "Foundry could not be reached within the request timeout."
            ) from None
        except AzureError:
            raise ProviderError(
                "Foundry authentication failed. Check sign-in and inference RBAC."
            ) from None
        except (ValueError, ValidationError, DecisionError):
            raise ProviderError("Foundry returned an invalid decision response.") from None
