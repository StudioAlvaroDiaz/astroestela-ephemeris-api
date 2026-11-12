import json
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security import sign
from tests.conftest import TEST_SECRET

CHART = {"datetime_local": "1990-05-15T14:30:00", "lat": 40.4168, "lon": -3.7038}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def signed_headers(method, path_qs, body=b"", ts=None, secret=TEST_SECRET):
    ts = str(ts or int(time.time()))
    return {
        "X-Astro-Timestamp": ts,
        "X-Astro-Signature": sign(secret, ts, method, path_qs, body),
        "Content-Type": "application/json",
    }


def post_chart(client, payload, **kw):
    body = json.dumps(payload).encode()
    return client.post("/v1/chart", content=body, headers=signed_headers("POST", "/v1/chart", body, **kw))


def test_health_is_public(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert r.headers["X-Source-Code"].startswith("https://")


def test_docs_are_disabled(client):
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404


def test_chart_requires_signature(client):
    assert client.post("/v1/chart", json=CHART).status_code == 401


def test_chart_with_valid_signature(client):
    r = post_chart(client, CHART)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["metadata"]["timezone"] == "Europe/Madrid"
    assert data["metadata"]["datetime_utc"].startswith("1990-05-15T12:30")


def test_wrong_secret_is_rejected(client):
    assert post_chart(client, CHART, secret="y" * 40).status_code == 401


def test_expired_signature_is_rejected(client):
    assert post_chart(client, CHART, ts=int(time.time()) - 3600).status_code == 401


def test_tampered_body_is_rejected(client):
    body = json.dumps(CHART).encode()
    headers = signed_headers("POST", "/v1/chart", body)
    tampered = json.dumps({**CHART, "lat": 10.0}).encode()
    assert client.post("/v1/chart", content=tampered, headers=headers).status_code == 401


def test_positions_signature_covers_query(client):
    path = "/v1/positions?datetime_utc=2026-11-11T19:00:00Z"
    r = client.get(path, headers=signed_headers("GET", path))
    assert r.status_code == 200
    assert "sun" in r.json()["positions"]
    other = "/v1/positions?datetime_utc=2026-11-12T19:00:00Z"
    assert client.get(other, headers=signed_headers("GET", path)).status_code == 401


def test_unknown_fields_and_bad_house_system(client):
    assert post_chart(client, {**CHART, "extra": 1}).status_code == 422
    assert post_chart(client, {**CHART, "house_system": "Z"}).status_code == 422


def test_both_datetimes_rejected(client):
    r = post_chart(client, {**CHART, "datetime_utc": "1990-05-15T12:30:00Z"})
    assert r.status_code == 422


def test_nonexistent_time_returns_clear_error(client):
    r = post_chart(client, {**CHART, "datetime_local": "2021-03-28T02:30:00"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "nonexistent_local_time"
