---
title: Ticker Lens demo specification
description: A minimal live-news demo of Microsoft-Decision-1.1 in Azure AI Foundry.
---

## Goal

Enter a U.S. stock ticker, fetch recent company news from Finnhub, and show how
Microsoft-Decision-1.1 turns the supplied text into fixed-choice decisions with
option probabilities. This is a read-only educational demo, not a trade
recommendation, price forecast, or fact-checking service.

## Demo flow

1. Enter one ticker (default `MSFT`) and select **Analyze news**.
2. The backend trims and uppercases the ticker, rejects invalid input, and
   requests the last seven days of [Finnhub Company News][finnhub]. Sort newest
   first, remove duplicates by Finnhub article ID or identical URL, and keep up
   to 10 articles.
3. Score each article with Foundry. Show the linked headline, publisher,
   publication time, input depth (headline only or headline and summary), and
   decision labels. An expandable row shows the input text, the questions, and
   the probability for each option so viewers can see how the API works.
4. Show one tally across the displayed articles: Bullish, Bearish, Neutral or
   mixed, and Unscored. Count each displayed article once, not
   each underlying event.
5. Show the total impact-weighted bullish and bearish probabilities and a
   directional gauge, separately from the article counts.

## Decision rubric

Use three `choice` questions in one request per article. Define each option in
the rubric and base all answers on the supplied news text for the target ticker.
Treat article text as data, not instructions.

* **Outlook.** Does the reported event help or hurt the company's business
  outlook over the next quarter? Options: Bullish, Bearish, Neutral or mixed.
  Neutral or mixed includes insufficient target-specific context for direction.
* **Potential impact.** If true, how consequential is the event for the
  company's business? Options: High, Medium, Low, Cannot tell.
* **Evidence shown.** What sourcing is visible in the supplied text? Options:
  Primary document or on-record source, Attributed secondary reporting,
  Speculation or unclear sourcing, Not enough context.

Use the model's selected outlook without a confidence cutoff; show its
probability even when confidence is low. Show an article as **Unscored** if its
model call fails or returns an invalid response. Keep failures separate from neutral. Impact is not a
prediction of price movement, and evidence shown is not a guarantee of accuracy.

For the news lean, multiply each scored article's bullish and bearish
probabilities by its expected impact (High = 1, Medium = 2/3, Low = 1/3,
Cannot tell = 0), then sum by direction. Include all scored stories, not Unscored.
Divide the net by total impact weight and multiply by 100. A rounded score
within five points of zero is balanced; zero directional mass means no signal.

## Implementation boundaries

* Serve a static, single-page UI and `POST /api/analyze` from one Python web
  process, locally or on Azure. The browser sends `{ticker}` and renders the
  returned ticker, date window, article rows, tally, and weighted news lean.
  Styling and layout can change without changing the rubric or scoring.
* Keep the Finnhub adapter, Foundry adapter, and decision logic separate from
  the UI. The decision module owns question definitions, response validation,
  outlook labels, tallying, and the weighted news lean. It can be exercised without a browser.
* Deploy `Microsoft-Decision-1.1` in an Azure AI Foundry project. The backend
  sends a direct REST `POST` to
  `<resource-endpoint>/providers/microsoft/v1/systemone`, not a chat endpoint.
  Pass the deployment name as `model`, the ticker and permitted headline and
  optional summary as `state`, and the rubric as `questions`. Read selected
  options and probabilities from `answers`. See the [Foundry API guide][foundry].
* Keep the Finnhub API key, Foundry endpoint, and deployment name in server
  configuration. Use Microsoft Entra ID for local Foundry authentication. Do
  not send credentials to the browser or include them in logs. Confirm Finnhub
  terms permit sending and displaying the selected fields before running the
  live demo. Link to the publisher; do not scrape or store full articles.

## Infrastructure and deployment

Use Bicep and Azure CLI, orchestrated by a Makefile. Provision infrastructure
with `az deployment group create` and publish application code with
`az webapp deploy`. No portal-only setup steps or agent framework are required.

* Host the UI and Python backend together on Linux Azure App Service with a
  small paid plan. Avoid containers, a registry, and a database for this demo.
* Provision the App Service plan, web app, Foundry resource and project,
  Decision 1.1 model deployment, managed identity, and inference role assignment
  through Bicep. Use the web app's managed identity for Foundry authentication.
* Accept subscription, resource group, location, resource-name prefix, and model
  deployment settings as inputs. Allow a separate supported model region.
  Bootstrap the resource group through the Makefile and reuse deployment outputs
  for app configuration rather than copying endpoints manually.
* Require Azure sign-in, deployment permissions, model availability/quota, and a
  Finnhub key as prerequisites. Supply the key through a secure parameter into
  server-side app settings, never committed files, deployment outputs, or logs.
* Keep hosted access restricted to the demo audience using App Service
  authentication. Confirm Finnhub usage rights before sharing the hosted demo.
  App Service and model inference incur Azure charges.

The Makefile is the documented entry point:

* `make run` starts the local app; `make test` runs focused tests.
* `make infra` creates or updates infrastructure and server configuration.
* `make deploy` packages and publishes the app to existing infrastructure.
* `make up` runs provisioning, deployment, and a health check, then prints the URL.
* `make smoke` checks deployed app health; document a separate authenticated,
  live ticker-analysis check to verify both external integrations.
* `make down` removes the demo resource group only after explicit confirmation.

Provisioning and deployment must be repeatable, fail visibly on errors, and
require no manual code changes between local and hosted execution.

## Acceptance criteria

* A live run for a ticker with recent coverage shows 1 to 10 distinct, linked
  Finnhub articles and real Foundry decisions. A run uses one Finnhub news call
  and at most one Foundry call per article, with bounded concurrency and timeouts.
* The tally adds up to the displayed row count. Tests with synthetic inputs and
  stubbed responses cover deduplication, low-confidence labels, and
  failed model calls without a browser or live credentials.
* Invalid input, no recent news, and upstream errors have distinct UI states.
  A failed model call does not hide the linked article or fabricate a score.
* Starting with the documented prerequisites, `make up` provisions all Azure
  resources and deploys a working app. Verify an authenticated live analysis,
  rerun deployment successfully, and confirm the hosted app uses managed
  identity rather than a Foundry API key.

Defer event clustering, SEC filings, streaming, persistence, and portfolio or
trading integration.

[finnhub]: https://finnhub.io/docs/api/company-news
[foundry]: https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-microsoft-decision
