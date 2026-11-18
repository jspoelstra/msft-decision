---
title: Ticker Lens
description: Live Finnhub news scored with Microsoft-Decision-1.1 on Azure AI Foundry.
---

**Turn a stock ticker into a readable view of recent company news.**
Ticker Lens is an educational demo of Microsoft-Decision-1.1 on Azure AI
Foundry. It shows what the model chose and how it scored the alternatives.

[Run locally](#run-locally-with-live-services) ·
[Deploy to Azure](#provision-and-deploy) ·
[Read the implementation spec](docs/spec.md)

![Ticker Lens dashboard showing bullish and bearish story counts, an impact-weighted gauge, and individual article scores](docs/images/ticker-lens-dashboard.png)

*Screenshots use fictional headlines and sample scores, not live market data.*

## What it does

1. **Find relevant stories.** Enter a U.S. ticker. Ticker Lens fetches live
   Finnhub news one UTC day at a time, newest first, until it finds 10 bullish
   or bearish stories or reaches the end of the lookback.
2. **Compare the results.** Read the story counts and impact-weighted news
   lean. The app skips neutral stories and reports how many it checked.
3. **Inspect a decision.** Expand a row to see the headline and summary sent
   to Foundry, the scoring rubric, and the probabilities for each option
   across business outlook, potential impact, and evidence shown.

![Expanded decision inspector showing the submitted headline and summary and the three outlook probabilities](docs/images/ticker-lens-inspector.png)

### How to read the news lean

The impact-weighted news lean sums bullish and bearish probability across
the displayed bullish or bearish stories. For each story, the app weights
both probabilities by expected impact: High = 1, Medium = 2/3, Low = 1/3,
and Cannot tell = 0. The gauge shows the difference divided by total impact
weight on a scale from -100 to +100. Rounded scores from -5 to +5 are
balanced; no directional weight means no signal. This is a summary of the
selected stories, not a probability of a price move or the full news mix.
Neutral or mixed stories are skipped; the UI reports how many were checked
and skipped. Scoring failures remain visible and do not count toward 10 matches.

Each scored article uses the model's selected Bullish, Bearish, or Neutral or
mixed outlook without a confidence cutoff. Neutral or mixed includes limited
context that does not establish direction. Probabilities remain visible;
failed or invalid responses stay Unscored, not neutral.

This is an educational demo, not investment advice, a price prediction, or
verification of news claims.
Only article IDs and identical URLs are deduplicated; syndicated stories can
still describe the same event.

## Prerequisites

* Python 3.11, [uv](https://docs.astral.sh/uv/), GNU Make, and Azure CLI
* An Azure subscription with billing enabled and Decision 1.1 quota in the
  selected region
* Permission to create resources, assign inference RBAC roles, and register
  single-tenant Microsoft Entra applications
* A Finnhub API key whose terms permit your intended display and hosted-model
  processing of headlines and summaries

The default deployment uses a paid Linux App Service B1 plan, plus metered
Foundry inference. It creates a new dedicated resource group. Nothing in
`make setup`, `make test`, `make check`, or `make run` provisions Azure resources.

## Install and test

```bash
make setup
make test
az bicep install
make check
cp .env.example .env
```

`make setup` resolves dependencies with uv and creates a local lock file.
Subsequent commands use that lock, including the requirements exported into
the deployment archive. The generated lock is local so a machine-specific
package mirror is not imposed on other developers. To update dependencies,
rerun `make setup` after editing the manifest. Set `UV_DEFAULT_INDEX` if your
environment requires a package mirror.

## Provision and deploy

Set `FINNHUB_API_KEY` in the ignored `.env` file. Do not paste credentials into
commands or commit them. Sign in, select your subscription, and provision:

```bash
az login
az account set --subscription YOUR_SUBSCRIPTION_ID
make up
```

`make up` creates or updates the infrastructure with Bicep, publishes a ZIP using
`az webapp deploy`, verifies `/health`, and prints the URL. Open the URL and sign
in with the deploying user's account to analyze a ticker.

The workflow creates a single-tenant Entra app registration and a 90-day login
secret. Deployment state, including that secret, lives under ignored `.azure`
with owner-only file permissions. Preserve this directory for repeat deployments
and cleanup. `make infra` renews the secret when fewer than two days remain.
The hosted app uses managed identity, not this login secret, for Foundry inference.

Configuration can be supplied as environment variables or Make arguments:

```bash
make up RESOURCE_GROUP=rg-ticker-lens-demo PREFIX=tickerlens \
  LOCATION=eastus2 MODEL_LOCATION=eastus2 MODEL_CAPACITY=30
```

Other inputs are `SUBSCRIPTION`, `DEPLOYMENT_NAME` (default `decision`), `MODEL_SKU`
(default `GlobalStandard`), `PLAN_SKU` (default `B1`), and `ALLOWED_USERS`
(comma-separated Entra user object IDs, defaulting to the deploying user).
Keep the resource group, subscription, and prefix consistent on subsequent runs.
The scripts refuse to reuse or delete groups without the demo ownership tag.
Changing region or model SKU requires checking availability and quota first.

| Target        | Action                                              |
|---------------|-----------------------------------------------------|
| `make run`    | Start the local UI and backend at localhost:8000     |
| `make test`   | Run isolated tests without credentials              |
| `make check`  | Run lint, type checking, and Bicep compilation        |
| `make package` | Build the deployment ZIP without Azure access      |
| `make infra`  | Provision Azure resources and server configuration  |
| `make deploy` | Package and publish to existing infrastructure      |
| `make smoke`  | Check the deployed app's public, non-sensitive health |
| `make down`   | Confirm, then remove the group and Entra registration |

The health endpoint verifies the process, not either external integration.
The UI, static assets, and analysis endpoint require App Service authentication
when hosted. Authentication is intentionally handled by Azure, not custom UI
code; locally the server binds only to loopback.

## Run locally with live services

After provisioning, get the Foundry endpoint and resource ID from deployment
outputs:

```bash
az deployment group show --resource-group rg-ticker-lens --name ticker-lens \
  --query properties.outputs
```

You can also use an existing Foundry resource with a Decision 1.1 deployment
without running `make up` or creating an app registration.

Set `AZURE_ENDPOINT` to the Foundry resource root URL, without
`/providers/microsoft` or a project path. The app appends the Decision API path.
Set `DEPLOYMENT_NAME` to the exact name shown in Foundry. Put both values in
`.env` and restart `make run` after editing the file.

Grant your signed-in user the `Cognitive Services User` role at the Foundry
resource scope if they do not already have it. Azure Contributor alone does
not grant inference.
The hosted identity already receives that role through Bicep.

```bash
az role assignment create \
  --assignee-object-id "$(az ad signed-in-user show --query id -o tsv)" \
  --assignee-principal-type User \
  --role "Cognitive Services User" \
  --scope YOUR_FOUNDRY_RESOURCE_ID
make run
```

Open <http://127.0.0.1:8000>. Without credentials, the UI and health endpoint
still load, but analysis reports the missing configuration rather than
substituting sample data.

Set `NEWS_LOOKBACK_DAYS` in `.env` to use a shorter lookback (1 to 7, default 7),
then restart `make run`. On Azure, set the same App Service environment variable.

After updating the app, reload the page before running another analysis. The
page uses versioned JavaScript and CSS URLs to avoid reusing outdated assets.

## Live verification and troubleshooting

1. Sign in to the hosted URL and analyze `MSFT` or another ticker with recent news.
2. Verify linked articles, inspect the supplied inputs and three probability
   distributions, and confirm the tally sums to the displayed row count.
3. If all rows are Unscored, inspect a row for the Foundry error. A healthy
   web app is not proof of working inference.
4. Rerun `make up` with the same inputs to verify repeatable provisioning and
   deployment. App Service settings contain no Foundry API key.

Allow several minutes for identity and RBAC changes to propagate. HTTP 429 means
the provider's quota/rate limit was reached; wait or adjust capacity. Scoring
uses at most three concurrent calls and does not retry, preserving a maximum
of one model request per scanned article. Scanning can require substantially
more than 10 inference calls, including neutral stories that are not displayed.
Each run uses one Finnhub request per fetched day, at most `NEWS_LOOKBACK_DAYS`
requests. The UI counts retrieved stories only from those fetched days, not the
entire potential lookback. Duplicate IDs and URLs are skipped across days.
After 180 seconds of retrieval and scoring, the app returns completed batches with an explicit
partial-results warning. Only one analysis runs at a time per Python process.

Provisioning fails before creating paid resources when the Finnhub key is
missing. Azure CLI failures are reported without dumping potentially sensitive
response bodies. For a failed ARM deployment, inspect the `ticker-lens`
deployment's operation details in the selected resource group. Do not share
deployment parameters or application settings in logs.

## Code layout

* `ticker_lens/decision.py` owns questions, response validation, review policy,
  and tallying without web-framework dependencies.
* `ticker_lens/providers.py` owns Finnhub and keyless Foundry HTTP adapters.
* `ticker_lens/service.py` handles article selection and bounded orchestration.
* `ticker_lens/app.py` serves the API and static UI from one Python process.
* `ticker_lens/static/` contains presentation-only HTML, CSS, and JavaScript.
* `infra/` and `scripts/deploy.py` implement the Makefile deployment workflow.

Foundry integration follows the
[Decision API guide](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-microsoft-decision).
