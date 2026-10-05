from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_compose_defaults_bind_services_to_loopback():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    postgres = (ROOT / "docker-compose.postgresql.yml").read_text(encoding="utf-8")

    required = [
        "${ALARM_RAG_BIND_ADDRESS:-127.0.0.1}:${ALARM_RAG_PORT:-8100}:8000",
        "${QDRANT_BIND_ADDRESS:-127.0.0.1}:${QDRANT_HTTP_PORT:-6333}:6333",
        "${N8N_BIND_ADDRESS:-127.0.0.1}:${N8N_PORT:-5678}:5678",
        "${POSTGRES_BIND_ADDRESS:-127.0.0.1}:${POSTGRES_EXPOSE_PORT:-5432}:5432",
    ]

    combined = f"{compose}\n{postgres}"
    missing = [item for item in required if item not in combined]
    assert missing == []


def test_proxy_sample_preserves_tls_and_readiness_limits():
    proxy = (ROOT / "deploy/nginx/alarm-rag-postgresql-tls.conf").read_text(encoding="utf-8")
    assert "listen 443 ssl" in proxy
    assert "proxy_pass http://127.0.0.1:8100" in proxy
    assert "location = /ready" in proxy
    assert "limit_req zone=ready_per_ip" in proxy
    assert "limit_req zone=ready_global" in proxy
    assert "limit_conn ready_conn_per_ip" in proxy
    assert "limit_conn ready_conn_global" in proxy


def test_postgresql_health_keeps_wal_archive_checks():
    health = (ROOT / "scripts/postgresql_health.py").read_text(encoding="utf-8")
    assert "--require-wal-archive" in health
    assert "pg_stat_archiver" in health
