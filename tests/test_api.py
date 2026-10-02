from datetime import date

import pytest
from fastapi.testclient import TestClient

import app.main as main


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test.db")
    main.init_db()
    with TestClient(main.app) as test_client:
        yield test_client


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_today_schedule_has_bom(client):
    response = client.get(
        "/api/schedules",
        params={"production_date": date.today().isoformat(), "production_line": "A"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2
    assert data[0]["bom"]
    assert data[0]["bom"][0]["standard_weight"] > 0


def test_draft_complete_and_trace(client):
    schedules = client.get(
        "/api/schedules",
        params={"production_date": date.today().isoformat(), "production_line": "B"},
    ).json()
    schedule = schedules[0]
    materials = [{
        "material_code": item["material_code"],
        "lots": [{
            "expiry_date": "2027-12-31",
            "received_date": date.today().isoformat(),
            "used_weight": item["standard_weight"],
        }],
    } for item in schedule["bom"]]

    draft = client.put(
        f"/api/records/{schedule['id']}/draft",
        json={"materials": materials},
    )
    assert draft.status_code == 200
    assert client.get(f"/api/records/{schedule['id']}/draft").json()["draft"]

    completed = client.post(
        f"/api/records/{schedule['id']}/complete",
        json={"actual_weight": schedule["planned_weight"], "materials": materials},
    )
    assert completed.status_code == 201
    assert client.get(f"/api/records/{schedule['id']}/draft").json()["draft"] is None

    traced = client.get(
        "/api/trace",
        params={"type": "product", "q": schedule["product_code"]},
    )
    assert traced.status_code == 200
    assert traced.json()[0]["materials"][0]["lots"][0]["material_batch"]
