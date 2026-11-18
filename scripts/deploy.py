"""Provision and publish Ticker Lens through the Makefile."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def az(*args: str) -> object:
    """Capture CLI output so secrets never reach the terminal."""
    completed = subprocess.run(
        ["az", *args, "--only-show-errors", "-o", "json"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        # Azure error bodies can include app settings; do not print raw output.
        raise RuntimeError(
            f"Azure CLI operation '{' '.join(args[:3])}' failed. "
            "Check permissions, region, quota, and Azure deployment operations."
        )
    return json.loads(completed.stdout) if completed.stdout.strip() else {}


def save_private(path: Path, value: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream)


def environment() -> tuple[dict[str, str], Path]:
    account = az("account", "show")
    if not isinstance(account, dict):
        raise RuntimeError("Run az login first.")
    subscription = os.getenv("SUBSCRIPTION") or account["id"]
    account = az("account", "show", "--subscription", subscription)
    if not isinstance(account, dict):
        raise RuntimeError("Unable to resolve the selected Azure subscription.")
    subscription = account["id"]
    group = os.getenv("RESOURCE_GROUP", "rg-ticker-lens")
    prefix = os.getenv("PREFIX", "tickerlens")
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,19}", prefix):
        raise RuntimeError("PREFIX must be 3-20 lowercase letters, digits, or hyphens.")
    suffix = hashlib.sha256(f"{subscription}/{group}".encode()).hexdigest()[:10]
    env = {
        **os.environ,
        "SUBSCRIPTION": subscription,
        "RESOURCE_GROUP": group,
        "APP_NAME": f"{prefix}-{suffix}",
        "LOCATION": os.getenv("LOCATION", "eastus2"),
        "MODEL_LOCATION": os.getenv("MODEL_LOCATION", os.getenv("LOCATION", "eastus2")),
        "DEPLOYMENT_NAME": os.getenv("DEPLOYMENT_NAME", "decision"),
        "MODEL_SKU": os.getenv("MODEL_SKU", "GlobalStandard"),
        "MODEL_CAPACITY": os.getenv("MODEL_CAPACITY", "30"),
        "PLAN_SKU": os.getenv("PLAN_SKU", "B1"),
        "TENANT_ID": account["tenantId"],
    }
    return env, ROOT / ".azure" / f"{suffix}.json"


def ensure_registration(env: dict[str, str], path: Path) -> dict:
    if path.exists():
        state = json.loads(path.read_text())
        if state["appName"] != env["APP_NAME"]:
            raise RuntimeError("PREFIX differs from this deployment's saved state.")
    else:
        user = az("ad", "signed-in-user", "show")
        if not isinstance(user, dict):
            raise RuntimeError("Interactive user sign-in is required for initial provisioning.")
        name = f"Ticker Lens {env['APP_NAME']}"
        matches = az("ad", "app", "list", "--display-name", name)
        if matches:
            raise RuntimeError(
                "An Entra registration already uses this deployment name but "
                "local ownership state is missing. Restore .azure state first."
            )
        app = az(
            "ad",
            "app",
            "create",
            "--display-name",
            name,
            "--sign-in-audience",
            "AzureADMyOrg",
            "--enable-id-token-issuance",
            "true",
            "--web-redirect-uris",
            f"https://{env['APP_NAME']}.azurewebsites.net/.auth/login/aad/callback",
        )
        if not isinstance(app, dict):
            raise RuntimeError("Entra did not return the application registration.")
        state = {
            "appName": env["APP_NAME"],
            "appId": app["appId"],
            "allowedUsers": os.getenv("ALLOWED_USERS", user["id"]),
        }
        save_private(path, state)
    principals = az("ad", "sp", "list", "--filter", f"appId eq '{state['appId']}'")
    if not principals:
        az("ad", "sp", "create", "--id", state["appId"])
    expiry = datetime.fromisoformat(state.get("expires", "2000-01-01T00:00:00+00:00"))
    if expiry < datetime.now(UTC) + timedelta(days=2):
        expires = datetime.now(UTC) + timedelta(days=90)
        secret = az(
            "ad",
            "app",
            "credential",
            "reset",
            "--id",
            state["appId"],
            "--end-date",
            expires.isoformat(),
            "--display-name",
            "ticker-lens-login",
        )
        if not isinstance(secret, dict):
            raise RuntimeError("Entra did not return the application credential.")
        state.update(secret=secret["password"], expires=expires.isoformat())
        save_private(path, state)
    return state


def provision(env: dict[str, str], path: Path) -> None:
    if not env.get("FINNHUB_API_KEY"):
        raise RuntimeError("Set FINNHUB_API_KEY before provisioning paid resources.")
    models = az(
        "cognitiveservices",
        "model",
        "list",
        "--location",
        env["MODEL_LOCATION"],
        "--subscription",
        env["SUBSCRIPTION"],
    )
    if not isinstance(models, list) or not any(
        model.get("model", {}).get("name") == "Microsoft-Decision-1.1"
        and any(sku["name"] == env["MODEL_SKU"] for sku in model["model"].get("skus", []))
        for model in models
    ):
        raise RuntimeError("Decision 1.1 or the selected SKU is unavailable in MODEL_LOCATION.")
    usage = az(
        "cognitiveservices",
        "usage",
        "list",
        "--location",
        env["MODEL_LOCATION"],
        "--subscription",
        env["SUBSCRIPTION"],
    )
    quota_name = f"AIServices.{env['MODEL_SKU']}.Microsoft-Decision-1.1"
    quotas = (
        [item for item in usage if item["name"]["value"] == quota_name]
        if isinstance(usage, list)
        else []
    )
    if not quotas or quotas[0]["limit"] < int(env["MODEL_CAPACITY"]):
        raise RuntimeError("Selected model capacity exceeds subscription quota in MODEL_LOCATION.")
    groups = az(
        "group",
        "list",
        "--subscription",
        env["SUBSCRIPTION"],
        "--query",
        f"[?name=='{env['RESOURCE_GROUP']}']",
    )
    if not isinstance(groups, list):
        raise RuntimeError("Unable to inspect Azure resource groups.")
    if groups and (groups[0].get("tags") or {}).get("tickerLens") != env["APP_NAME"]:
        raise RuntimeError("Refusing to use a resource group not owned by this demo.")
    state = ensure_registration(env, path)
    az(
        "group",
        "create",
        "--subscription",
        env["SUBSCRIPTION"],
        "--name",
        env["RESOURCE_GROUP"],
        "--location",
        env["LOCATION"],
        "--tags",
        f"tickerLens={env['APP_NAME']}",
    )
    env.update(
        AUTH_CLIENT_ID=state["appId"],
        AUTH_CLIENT_SECRET=state["secret"],
        ALLOWED_USERS=os.getenv("ALLOWED_USERS", state["allowedUsers"]),
    )
    print(
        f"Provisioning {env['RESOURCE_GROUP']} in {env['SUBSCRIPTION']}; "
        f"web: {env['LOCATION']}, model: {env['MODEL_LOCATION']}.",
        flush=True,
    )
    result = subprocess.run(
        [
            "az",
            "deployment",
            "group",
            "create",
            "--subscription",
            env["SUBSCRIPTION"],
            "--resource-group",
            env["RESOURCE_GROUP"],
            "--name",
            "ticker-lens",
            "--parameters",
            str(ROOT / "infra/main.bicepparam"),
            "--only-show-errors",
            "-o",
            "none",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            "Bicep deployment failed. Inspect Azure deployment operations "
            "for 'ticker-lens' in the selected resource group."
        )
    deployed_url = outputs(env)["appUrl"]["value"]
    az(
        "ad",
        "app",
        "update",
        "--id",
        state["appId"],
        "--web-redirect-uris",
        f"{deployed_url}/.auth/login/aad/callback",
    )
    print("Infrastructure ready. Entra/RBAC propagation may take several minutes.")


def outputs(env: dict[str, str]) -> dict:
    deployment = az(
        "deployment",
        "group",
        "show",
        "--subscription",
        env["SUBSCRIPTION"],
        "--resource-group",
        env["RESOURCE_GROUP"],
        "--name",
        "ticker-lens",
    )
    if not isinstance(deployment, dict):
        raise RuntimeError("No deployment found. Run make infra first.")
    return deployment["properties"]["outputs"]


def package() -> Path:
    """Build the same ZIP locally that is uploaded to App Service."""
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    requirements = subprocess.run(
        [
            "uv",
            "export",
            "--frozen",
            "--no-dev",
            "--no-emit-project",
            "--no-hashes",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    archive_path = dist / "app.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("requirements.txt", requirements)
        for source in (ROOT / "ticker_lens").rglob("*"):
            if source.is_file() and "__pycache__" not in source.parts:
                archive.write(source, source.relative_to(ROOT))
    return archive_path


def deploy(env: dict[str, str]) -> None:
    info = outputs(env)
    archive_path = package()
    az(
        "webapp",
        "deploy",
        "--subscription",
        env["SUBSCRIPTION"],
        "--resource-group",
        env["RESOURCE_GROUP"],
        "--name",
        info["webAppName"]["value"],
        "--src-path",
        str(archive_path),
        "--type",
        "zip",
        "--timeout",
        "600000",
    )
    print(f"Published {info['appUrl']['value']}")


def smoke(env: dict[str, str]) -> None:
    url = outputs(env)["appUrl"]["value"]
    last_error = "not started"
    for attempt in range(24):
        try:
            with urlopen(f"{url}/health", timeout=10) as response:
                if json.load(response) == {"status": "ok"}:
                    print(f"Healthy: {url}\nSign in there to run a live ticker analysis.")
                    return
                last_error = "Unexpected health response."
        except (URLError, TimeoutError, ValueError) as exc:
            last_error = str(exc)
        if attempt < 23:
            time.sleep(5)
    raise RuntimeError(f"Health check failed: {last_error}")


def down(env: dict[str, str], path: Path) -> None:
    group = env["RESOURCE_GROUP"]
    confirmation = input(f"Type {group} to delete the demo resources and Entra registration: ")
    if confirmation != group:
        raise RuntimeError("Deletion cancelled.")
    resource = az("group", "show", "--name", group, "--subscription", env["SUBSCRIPTION"])
    if (
        not isinstance(resource, dict)
        or resource.get("tags", {}).get("tickerLens") != env["APP_NAME"]
    ):
        raise RuntimeError("Refusing to delete a resource group not owned by this demo.")
    az("group", "delete", "--name", group, "--subscription", env["SUBSCRIPTION"], "--yes")
    if path.exists():
        state = json.loads(path.read_text())
        az("ad", "app", "delete", "--id", state["appId"])
        path.unlink()
    print("Demo resources removed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["infra", "package", "deploy", "smoke", "down"])
    args = parser.parse_args()
    try:
        if args.action == "package":
            print(package())
            return 0
        env, path = environment()
        if args.action == "infra":
            provision(env, path)
        elif args.action == "deploy":
            deploy(env)
        elif args.action == "smoke":
            smoke(env)
        else:
            down(env, path)
        return 0
    except (RuntimeError, subprocess.SubprocessError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
