"""HTTP entry point; run with uvicorn ticker_lens.app:app."""

import asyncio
import logging
from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path
from typing import Annotated

import httpx
from azure.identity.aio import DefaultAzureCredential
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ticker_lens.decision import THRESHOLD, questions_payload
from ticker_lens.providers import ProviderError, Providers, Settings
from ticker_lens.service import Analysis, analyze, normalize_ticker

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logging.getLogger("azure").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"


class AnalyzeRequest(BaseModel):
    ticker: Annotated[str, Field(min_length=1, max_length=32)]


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings.from_env()
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        async with DefaultAzureCredential(process_timeout=10) as credential:
            app.state.providers = Providers(settings, client, credential)
            app.state.analysis_lock = asyncio.Lock()
            yield


app = FastAPI(title="Ticker Lens", lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def response_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; script-src 'self'; "
        "img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'"
    )
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index() -> HTMLResponse:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for asset in ("app.js", "style.css"):
        version = sha256((STATIC / asset).read_bytes()).hexdigest()[:16]
        url = f"/static/{asset}"
        html = html.replace(f'"{url}"', f'"{url}?v={version}"')
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/analyze")
async def analyze_news(body: AnalyzeRequest, request: Request):
    try:
        ticker = normalize_ticker(body.ticker)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    backend: Providers = request.app.state.providers
    lock: asyncio.Lock = request.app.state.analysis_lock
    if lock.locked():
        raise HTTPException(409, "An analysis is already running. Please wait and try again.")
    try:
        backend.settings.require_configured()
        async with lock:
            async with asyncio.timeout(185):
                result: Analysis = await analyze(ticker, backend)
        return {
            **result.model_dump(mode="json"),
            "questions": questions_payload(),
            "threshold": THRESHOLD,
        }
    except ProviderError as exc:
        logger.warning("Analysis unavailable: %s", exc)
        raise HTTPException(503, str(exc)) from None
    except TimeoutError:
        logger.warning("Analysis exceeded its overall timeout")
        raise HTTPException(504, "Analysis timed out. Please try again later.") from None
