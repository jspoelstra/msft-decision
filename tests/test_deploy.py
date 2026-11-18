"""Verify deployment guards, repeatability, and credential handling without Azure writes."""

import importlib.util
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "deploy", Path(__file__).resolve().parents[1] / "scripts" / "deploy.py"
)
assert SPEC is not None and SPEC.loader is not None
deploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy)


def test_given_missing_news_key_when_provisioning_then_creates_nothing(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Provisioning must not call Azure without a news key.")

    monkeypatch.setattr(deploy, "az", forbidden)

    with pytest.raises(RuntimeError, match="FINNHUB_API_KEY"):
        deploy.provision({}, tmp_path / "state.json")


def test_given_existing_valid_registration_when_reprovisioning_then_reuses_credential(
    tmp_path, monkeypatch
):
    state_path = tmp_path / "state.json"
    original = {
        "appName": "demo",
        "appId": "client-id",
        "secret": "not-real",
        "allowedUsers": "user-id",
        "expires": "2099-01-01T00:00:00+00:00",
    }
    deploy.save_private(state_path, original)
    calls = []

    def azure(*args):
        calls.append(args)
        if args[:3] == ("ad", "sp", "list"):
            return [{"id": "existing-principal"}]
        pytest.fail("Existing unexpired credentials must not be reset.")

    monkeypatch.setattr(deploy, "az", azure)

    result = deploy.ensure_registration({"APP_NAME": "demo"}, state_path)

    assert result == original
    assert len(calls) == 1
    assert stat.S_IMODE(os.stat(state_path).st_mode) == 0o600


def test_given_azure_cli_error_when_running_then_does_not_echo_secret(monkeypatch):
    monkeypatch.setattr(
        deploy.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="SECRET_VALUE_MUST_NOT_LEAK"
        ),
    )

    with pytest.raises(RuntimeError) as error:
        deploy.az("deployment", "group", "show")

    assert "SECRET_VALUE" not in str(error.value)
    assert "failed" in str(error.value)


def test_given_state_file_when_writing_then_preserves_json_with_private_permissions(tmp_path):
    path = tmp_path / "state.json"
    path.touch(mode=0o644)

    deploy.save_private(path, {"appId": "test-client"})

    assert json.loads(path.read_text()) == {"appId": "test-client"}
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
