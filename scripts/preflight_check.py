import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from env_utils import ROOT, load_project_env


sys.path.insert(0, str(ROOT))
load_project_env()

from secret_values import SecretConfigError, secret_value


PLACEHOLDER_VALUES = {
    "change-me-now",
    "replace-with-a-random-trigger-token",
    "replace-with-a-long-random-index-signing-key",
    "replace-with-a-long-random-string",
    "replace-with-a-long-random-qdrant-api-key",
}


@dataclass
class Check:
    name: str
    status: str
    detail: str


def record(results: list[Check], name: str, ok: bool, detail: str, warn: bool = False) -> None:
    status = "PASS" if ok else ("WARN" if warn else "FAIL")
    results.append(Check(name, status, detail))


def env_value(name: str) -> str:
    return os.getenv(name, "").strip()


def automation_enabled() -> bool:
    return "automation" in {item.strip() for item in env_value("COMPOSE_PROFILES").split(",")}


def check_env(results: list[Check], *, automation: bool | None = None) -> None:
    env_path = ROOT / ".env"
    record(results, "env:file", env_path.exists(), ".env exists" if env_path.exists() else ".env is missing")
    required = [
        "ADMIN_INITIAL_PASSWORD",
        "ALARM_RAG_TRIGGER_TOKEN",
        "ALARM_RAG_INDEX_SIGNING_KEY",
        "QDRANT_API_KEY",
    ]
    if automation is True or (automation is None and automation_enabled()):
        required.append("N8N_ENCRYPTION_KEY")
    for key in required:
        try:
            value = secret_value(key).strip()
        except SecretConfigError as exc:
            record(results, f"env:{key}", False, str(exc))
            continue
        if not value:
            record(results, f"env:{key}", False, "missing")
            continue
        if value in PLACEHOLDER_VALUES:
            record(results, f"env:{key}", False, "still uses placeholder")
            continue
        record(results, f"env:{key}", True, "set")


def check_ports(results: list[Check], *, automation: bool | None = None) -> None:
    ports = {
        "ALARM_RAG_PORT": "8100",
        "QDRANT_HTTP_PORT": "6333",
    }
    if automation is True or (automation is None and automation_enabled()):
        ports["N8N_PORT"] = "5678"
    for key, default in ports.items():
        value = env_value(key) or default
        try:
            port = int(value)
        except ValueError:
            record(results, f"port:{key}", False, f"invalid integer: {value}")
            continue
        record(results, f"port:{key}", 1 <= port <= 65535, str(port))


def check_bind_addresses(results: list[Check], *, automation: bool | None = None) -> None:
    keys = ["ALARM_RAG_BIND_ADDRESS", "QDRANT_BIND_ADDRESS"]
    if automation is True or (automation is None and automation_enabled()):
        keys.append("N8N_BIND_ADDRESS")
    for key in keys:
        value = env_value(key) or "127.0.0.1"
        if value in {"127.0.0.1", "localhost", "::1"}:
            record(results, f"bind:{key}", True, value)
        elif value in {"0.0.0.0", "::"}:
            record(results, f"bind:{key}", False, f"{value} exposes the service beyond loopback", warn=True)
        else:
            record(results, f"bind:{key}", False, value, warn=True)


def check_qdrant_transport(results: list[Check]) -> None:
    host = env_value("QDRANT_HOST") or "qdrant"
    https_enabled = (env_value("QDRANT_HTTPS") or "false").lower() in {"1", "true", "yes", "on"}
    trusted_hosts = {
        item.strip().lower()
        for item in (
            env_value("QDRANT_INSECURE_TRUSTED_HOSTS") or "qdrant,localhost,127.0.0.1,::1"
        ).split(",")
        if item.strip()
    }
    if https_enabled:
        record(results, "qdrant:transport", True, f"TLS enabled for {host}")
    elif host.lower() in trusted_hosts:
        is_local_default = host.lower() in {"qdrant", "localhost", "127.0.0.1", "::1"}
        record(
            results,
            "qdrant:transport",
            is_local_default,
            f"authenticated HTTP restricted to trusted host {host}",
            warn=not is_local_default,
        )
    else:
        record(
            results,
            "qdrant:transport",
            False,
            f"remote host {host} requires QDRANT_HTTPS=true or an explicit trusted private-network entry",
        )


def check_paths(results: list[Check]) -> None:
    for name in ["alarm_db", "data", "backups"]:
        path = Path(env_value("DB_PATH") or "alarm_db") if name == "alarm_db" else Path(name)
        if not path.is_absolute():
            path = ROOT / path
        if not path.exists():
            record(results, f"path:{name}", False, f"not created yet: {path}", warn=True)
        else:
            record(results, f"path:{name}", path.is_dir(), str(path))


def check_index_signatures(results: list[Check]) -> None:
    from signed_pickle import SignedPickleError, verify_signed_pickle

    index_dir = Path(env_value("DB_PATH") or "alarm_db")
    if not index_dir.is_absolute():
        index_dir = ROOT / index_dir
    paths = sorted(index_dir.glob("bm25_*.pkl")) if index_dir.is_dir() else []
    if not paths:
        record(results, "index-signatures", True, "no local BM25 indexes")
        return
    failures = []
    for path in paths:
        try:
            verify_signed_pickle(path)
        except (OSError, SignedPickleError) as exc:
            failures.append(f"{path.name}: {exc}")
    record(
        results,
        "index-signatures",
        not failures,
        f"verified {len(paths)} index(es)" if not failures else "; ".join(failures),
    )


def check_compose(results: list[Check], *, automation: bool | None = None) -> None:
    automation = automation if automation is not None else automation_enabled()
    compose_file = ROOT / "docker-compose.yml"
    record(results, "compose:file", compose_file.exists(), "docker-compose.yml exists" if compose_file.exists() else "missing")
    if not compose_file.exists():
        return
    compose_text = compose_file.read_text(encoding="utf-8")
    required_alarm_env = [
        "ALARM_RAG_ENV",
        "ADMIN_INITIAL_PASSWORD",
        "ALARM_RAG_TRIGGER_TOKEN",
        "ALARM_RAG_INDEX_SIGNING_KEY",
        "DB_PATH: /app/alarm_db",
        "HF_HOME: /app/hf_cache",
        "VECTOR_STORE",
        "QDRANT_HOST: qdrant",
        "OLLAMA_URL",
        "OLLAMA_MODEL",
    ]
    for key in required_alarm_env:
        record(
            results,
            f"compose:alarm-env:{key.split(':', 1)[0]}",
            key in compose_text,
            "configured" if key in compose_text else "missing",
        )
    for volume in ["./alarm_db:/app/alarm_db", "./hf_cache:/app/hf_cache", "./qdrant_data:/qdrant/storage"]:
        record(
            results,
            f"compose:volume:{volume.split(':', 1)[0]}",
            volume in compose_text,
            "configured" if volume in compose_text else "missing",
        )
    record(
        results,
        "compose:alarm-healthcheck",
        "http://localhost:8000/ready" in compose_text,
        "configured" if "http://localhost:8000/ready" in compose_text else "missing",
    )
    if automation:
        record(
            results,
            "compose:n8n-healthcheck",
            "http://127.0.0.1:5678/healthz" in compose_text,
            "configured" if "http://127.0.0.1:5678/healthz" in compose_text else "missing",
        )
    bindings = {
        "alarm-port-bind": "${ALARM_RAG_BIND_ADDRESS:-127.0.0.1}:${ALARM_RAG_PORT:-8100}:8000",
        "qdrant-port-bind": "${QDRANT_BIND_ADDRESS:-127.0.0.1}:${QDRANT_HTTP_PORT:-6333}:6333",
    }
    if automation:
        bindings["n8n-port-bind"] = "${N8N_BIND_ADDRESS:-127.0.0.1}:${N8N_PORT:-5678}:5678"
    for service, expected in bindings.items():
        record(
            results,
            f"compose:{service}",
            expected in compose_text,
            "configured" if expected in compose_text else "missing",
        )
    n8n_keys = [
        "N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS",
        "N8N_RUNNERS_ENABLED",
        "DB_SQLITE_POOL_SIZE",
        "N8N_BLOCK_ENV_ACCESS_IN_NODE",
        "N8N_GIT_NODE_DISABLE_BARE_REPOS",
        "N8N_DIAGNOSTICS_ENABLED",
        "N8N_PERSONALIZATION_ENABLED",
        "N8N_VERSION_NOTIFICATIONS_ENABLED",
    ]
    for key in n8n_keys if automation else []:
        record(
            results,
            f"compose:{key}",
            key in compose_text,
            "configured" if key in compose_text else "missing",
        )
    record(
        results,
        "compose:QDRANT__TELEMETRY_DISABLED",
        "QDRANT__TELEMETRY_DISABLED" in compose_text,
        "configured" if "QDRANT__TELEMETRY_DISABLED" in compose_text else "missing",
    )
    try:
        completed = subprocess.run(
            ["docker", "compose", *(["--profile", "automation"] if automation else []), "config", "--quiet"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        record(results, "compose:config", False, str(exc), warn=True)
        return
    detail = completed.stderr.strip() or completed.stdout.strip() or "config ok"
    record(results, "compose:config", completed.returncode == 0, detail)


def check_n8n_workflow(results: list[Check]) -> None:
    from n8n_workflow_check import load_workflow, validate_workflow

    workflow = ROOT / "mock_data" / "n8n_mock_workflow.json"
    try:
        workflow_data = load_workflow(workflow)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        record(results, "n8n:workflow", False, str(exc))
        return
    for item in validate_workflow(workflow_data):
        record(results, f"n8n:{item.name}", item.status == "PASS", item.detail)


def check_model_cache(results: list[Check], require_models: bool) -> None:
    from rag_engine import model_cache_status

    status = model_cache_status()
    detail = "ready" if status["ready"] else "missing local model cache"
    record(results, "model-cache", status["ready"], detail, warn=not require_models)


def check_ollama(results: list[Check], require_model: bool = False, *, url: str = "") -> None:
    endpoint = (url or env_value("OLLAMA_URL") or "http://127.0.0.1:11434").rstrip("/")
    model = env_value("OLLAMA_MODEL") or "gemma4:e2b"
    try:
        # Local inference must not be routed through an environment HTTP proxy.
        with httpx.Client(timeout=5.0, trust_env=False) as client:
            response = client.get(f"{endpoint}/api/tags")
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
            raise ValueError("invalid model list")
        names = set()
        for item in payload["models"]:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise ValueError("invalid model entry")
            names.add(item["name"])
    except (httpx.HTTPError, httpx.InvalidURL, ValueError):
        record(
            results, "ollama:service", False,
            "cannot read /api/tags; check Ollama is running and OLLAMA_URL is reachable "
            "from this process (host check: --ollama-url http://127.0.0.1:11434)",
            warn=not require_model,
        )
        return
    record(results, "ollama:service", True, "local model API reachable")
    # Ollama lists an explicit :latest even when configuration omits the tag.
    expected = model if ":" in model.rsplit("/", 1)[-1] else f"{model}:latest"
    installed = expected in names
    record(
        results, "ollama:model", installed,
        f"{model} installed (generation not tested)" if installed else f"{model} missing; run ollama pull {model}",
        warn=not require_model,
    )


def print_report(results: list[Check]) -> None:
    print("\nAlarm RAG Preflight")
    print("-" * 72)
    for item in results:
        print(f"[{item.status:<4}] {item.name:<24} {item.detail}")
    print("-" * 72)
    print(
        "PASS={pass_count} WARN={warn_count} FAIL={fail_count}".format(
            pass_count=sum(item.status == "PASS" for item in results),
            warn_count=sum(item.status == "WARN" for item in results),
            fail_count=sum(item.status == "FAIL" for item in results),
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Alarm RAG standalone deployment prerequisites")
    parser.add_argument("--require-model-cache", action="store_true", help="fail if HF model cache is missing")
    parser.add_argument("--require-ollama-model", action="store_true", help="fail if Ollama or the configured model is unavailable")
    parser.add_argument("--ollama-url", default="", help="override Ollama URL for this check only (e.g. host loopback)")
    parser.add_argument("--with-automation", action="store_true", help="also validate optional n8n automation")
    args = parser.parse_args()

    results: list[Check] = []
    automation = args.with_automation or automation_enabled()
    record(results, "automation", True, "enabled" if automation else "disabled; n8n checks skipped")
    check_env(results, automation=automation)
    check_ports(results, automation=automation)
    check_bind_addresses(results, automation=automation)
    check_qdrant_transport(results)
    check_paths(results)
    check_index_signatures(results)
    check_compose(results, automation=automation)
    if automation:
        check_n8n_workflow(results)
    check_ollama(results, args.require_ollama_model, url=args.ollama_url)
    check_model_cache(results, args.require_model_cache)
    print_report(results)
    return 1 if any(item.status == "FAIL" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
