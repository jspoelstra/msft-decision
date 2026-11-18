SHELL := /bin/bash
.DEFAULT_GOAL := help
.NOTPARALLEL: up

RESOURCE_GROUP ?= rg-ticker-lens
LOCATION ?= eastus2
MODEL_LOCATION ?= $(LOCATION)
PREFIX ?= tickerlens
MODEL_SKU ?= GlobalStandard
MODEL_CAPACITY ?= 30
PLAN_SKU ?= B1
ENV_FILE ?= .env
ENV_OPTION := $(if $(wildcard $(ENV_FILE)),--env-file $(ENV_FILE),)
export RESOURCE_GROUP LOCATION MODEL_LOCATION PREFIX MODEL_SKU MODEL_CAPACITY PLAN_SKU

infra deploy smoke down: export DEPLOYMENT_NAME ?= decision

.PHONY: help setup run test check package infra deploy up smoke down

help:
	@printf '%s\n' 'setup / run / test / check / package' 'infra / deploy / up / smoke / down' \
	  'See README.md for credentials, Azure prerequisites, and costs.'

setup:
	uv sync --python 3.11

run:
	uv run --frozen $(ENV_OPTION) uvicorn ticker_lens.app:app --reload --host 127.0.0.1 --port 8000

test:
	uv run --frozen pytest -q

check:
	uv run --frozen ruff check ticker_lens scripts tests
	uv run --frozen pyright
	az bicep build --file infra/main.bicep --stdout > /dev/null

infra:
	uv run --frozen $(ENV_OPTION) python scripts/deploy.py infra

package:
	uv run --frozen python scripts/deploy.py package

deploy:
	uv run --frozen $(ENV_OPTION) python scripts/deploy.py deploy

up: infra deploy smoke

smoke:
	uv run --frozen $(ENV_OPTION) python scripts/deploy.py smoke

down:
	uv run --frozen $(ENV_OPTION) python scripts/deploy.py down
