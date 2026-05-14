"""
Tests for dashboard/app.py API endpoints.
All tests monkeypatch `dashboard.app.query` — no live DB required.
"""

import pytest
from fastapi.testclient import TestClient

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dashboard.app import app

client = TestClient(app)


# ── helpers ──────────────────────────────────────────────────────────────────

def _patch(monkeypatch, return_value):
    """Replace dashboard.app.query with a callable returning return_value."""
    import dashboard.app as mod
    monkeypatch.setattr(mod, "query", lambda *a, **kw: return_value)


def _patch_seq(monkeypatch, responses):
    """Return successive responses for successive query() calls."""
    import dashboard.app as mod
    it = iter(responses)
    monkeypatch.setattr(mod, "query", lambda *a, **kw: next(it))


# ── /api/now ─────────────────────────────────────────────────────────────────

def test_now_returns_first_row(monkeypatch):
    row = {
        "period_utc": "2024-01-01T12:00:00",
        "price_p_kwh": 14.5,
        "carbon_gco2_kwh": 210,
        "intensity_index": "moderate",
        "renewable_pct": 38.0,
        "window_score": 62,
        "recommendation": "Good — go for it",
        "rank": 3,
        "next_period_utc": "2024-01-01T12:30:00",
        "next_price": 11.2,
        "next_carbon": 190,
        "next_score": 74,
        "next_recommendation": "Good — go for it",
    }
    _patch(monkeypatch, [row])
    r = client.get("/api/now")
    assert r.status_code == 200
    assert r.json()["price_p_kwh"] == 14.5


def test_now_empty_db_returns_empty_dict(monkeypatch):
    _patch(monkeypatch, [])
    r = client.get("/api/now")
    assert r.status_code == 200
    assert r.json() == {}


# ── /api/appliance-windows ────────────────────────────────────────────────────

def _make_price_rows(n, price_start=10.0, carbon_start=200):
    """Build n half-hourly rows with linearly increasing price + carbon."""
    from datetime import datetime, timedelta
    base = datetime(2024, 1, 1, 12, 0)
    rows = []
    for i in range(n):
        rows.append({
            "period_utc": (base + timedelta(minutes=30 * i)).isoformat(),
            "price_p_kwh":    round(price_start + i * 0.5, 2),
            "carbon_gco2_kwh": carbon_start + i * 5,
            "renewable_pct":  40.0,
        })
    return rows


def test_appliance_windows_returns_top5(monkeypatch):
    _patch(monkeypatch, _make_price_rows(20))
    r = client.get("/api/appliance-windows?hours=1")
    assert r.status_code == 200
    data = r.json()
    assert len(data) <= 5
    # best window should be first (earliest = cheapest = highest score)
    assert data[0]["score"] >= data[-1]["score"]


def test_appliance_windows_insufficient_rows(monkeypatch):
    _patch(monkeypatch, _make_price_rows(1))
    # hours=2 → needs 4 slots; only 1 available
    r = client.get("/api/appliance-windows?hours=2")
    assert r.status_code == 200
    assert r.json() == []


def test_appliance_windows_empty_db(monkeypatch):
    _patch(monkeypatch, [])
    r = client.get("/api/appliance-windows?hours=1")
    assert r.status_code == 200
    assert r.json() == []


def test_appliance_windows_all_same_price(monkeypatch):
    """All windows identical → scoring should not crash (p_range = 0 guard)."""
    rows = [
        {"period_utc": f"2024-01-01T{12+i//2:02d}:{30*(i%2):02d}:00",
         "price_p_kwh": 15.0, "carbon_gco2_kwh": 250, "renewable_pct": 35.0}
        for i in range(10)
    ]
    _patch(monkeypatch, rows)
    r = client.get("/api/appliance-windows?hours=1")
    assert r.status_code == 200


# ── /api/windows-by-day ───────────────────────────────────────────────────────

def _make_windows_by_day_rows():
    """Two days, varying price + carbon for score coverage."""
    return [
        {"period_utc": "2024-01-01T02:00:00", "price_p_kwh": 8.0,  "carbon_gco2_kwh": 100, "renewable_pct": 50.0, "intensity_index": "low"},
        {"period_utc": "2024-01-01T14:00:00", "price_p_kwh": 25.0, "carbon_gco2_kwh": 400, "renewable_pct": 20.0, "intensity_index": "high"},
        {"period_utc": "2024-01-02T03:00:00", "price_p_kwh": 10.0, "carbon_gco2_kwh": 150, "renewable_pct": 45.0, "intensity_index": "low"},
        {"period_utc": "2024-01-02T18:00:00", "price_p_kwh": 28.0, "carbon_gco2_kwh": 420, "renewable_pct": 15.0, "intensity_index": "high"},
    ]


def test_windows_by_day_groups_by_date(monkeypatch):
    _patch(monkeypatch, _make_windows_by_day_rows())
    r = client.get("/api/windows-by-day")
    assert r.status_code == 200
    data = r.json()
    assert "2024-01-01" in data
    assert "2024-01-02" in data


def test_windows_by_day_sorted_by_score_desc(monkeypatch):
    _patch(monkeypatch, _make_windows_by_day_rows())
    r = client.get("/api/windows-by-day")
    data = r.json()
    for day_rows in data.values():
        scores = [row["score"] for row in day_rows]
        assert scores == sorted(scores, reverse=True)


def test_windows_by_day_recommendation_labels(monkeypatch):
    """Score ≥ 75 → 'Excellent', ≥ 55 → 'Good', ≥ 35 → 'Fair', else 'Poor'."""
    _patch(monkeypatch, _make_windows_by_day_rows())
    r = client.get("/api/windows-by-day")
    data = r.json()
    for day_rows in data.values():
        for row in day_rows:
            s = row["score"]
            rec = row["recommendation"]
            if s >= 75:
                assert "Excellent" in rec
            elif s >= 55:
                assert "Good" in rec
            elif s >= 35:
                assert "Fair" in rec
            else:
                assert "Poor" in rec


def test_windows_by_day_empty_db(monkeypatch):
    _patch(monkeypatch, [])
    r = client.get("/api/windows-by-day")
    assert r.status_code == 200
    assert r.json() == {}


# ── /api/combined-heatmap ─────────────────────────────────────────────────────

def _make_heatmap_rows():
    rows = []
    for dow in range(7):
        for hour in range(24):
            rows.append({
                "hour_of_day": hour,
                "day_of_week": dow,
                "day_name": ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][dow],
                "avg_price_p_kwh": 10.0 + hour * 0.5 + dow * 0.2,
                "avg_carbon": 200 + hour * 3 + dow * 5,
            })
    return rows


def test_combined_heatmap_adds_score(monkeypatch):
    _patch(monkeypatch, _make_heatmap_rows())
    r = client.get("/api/combined-heatmap")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 168
    for row in data:
        assert 0 <= row["score"] <= 100


def test_combined_heatmap_empty_db(monkeypatch):
    _patch(monkeypatch, [])
    r = client.get("/api/combined-heatmap")
    assert r.status_code == 200
    assert r.json() == []


# ── /api/fuel-mix ─────────────────────────────────────────────────────────────

def test_fuel_mix_pivot(monkeypatch):
    _patch(monkeypatch, [
        {"hour_utc": "2024-01-01T12:00:00", "fuel_type": "WIND",   "generation_mw": 5000},
        {"hour_utc": "2024-01-01T12:00:00", "fuel_type": "NUCLEAR","generation_mw": 3000},
        {"hour_utc": "2024-01-01T13:00:00", "fuel_type": "WIND",   "generation_mw": 5500},
    ])
    r = client.get("/api/fuel-mix")
    assert r.status_code == 200
    data = r.json()
    assert "labels" in data and "fuels" in data
    assert "WIND" in data["fuels"]
    assert "NUCLEAR" in data["fuels"]
    # 2 distinct hours
    assert len(data["labels"]) == 2
    # NUCLEAR absent at T13 (label[0] after DESC→ASC reversal) → filled with 0
    assert data["fuels"]["NUCLEAR"][0] == 0


def test_fuel_mix_empty_db(monkeypatch):
    _patch(monkeypatch, [])
    r = client.get("/api/fuel-mix")
    assert r.status_code == 200
    data = r.json()
    assert data == {"labels": [], "fuels": {}}


# ── /api/best-windows ─────────────────────────────────────────────────────────

def test_best_windows_passthrough(monkeypatch):
    rows = [
        {"rank": 1, "period_utc": "2024-01-01T02:00:00", "period_to": "2024-01-01T02:30:00",
         "price_p_kwh": 8.0, "carbon_gco2_kwh": 120, "intensity_index": "low",
         "renewable_pct": 55.0, "window_score": 91, "recommendation": "Excellent — run anything"},
    ]
    _patch(monkeypatch, rows)
    r = client.get("/api/best-windows")
    assert r.status_code == 200
    assert r.json()[0]["rank"] == 1


# ── /api/regional-carbon ─────────────────────────────────────────────────────

def test_regional_carbon_passthrough(monkeypatch):
    rows = [
        {"shortname": "SW", "full_name": "South West England", "intensity_actual": 140, "intensity_band": "low"},
        {"shortname": "NE", "full_name": "North East England",  "intensity_actual": 210, "intensity_band": "moderate"},
    ]
    _patch(monkeypatch, rows)
    r = client.get("/api/regional-carbon")
    assert r.status_code == 200
    assert len(r.json()) == 2


# ── /api/kpi ─────────────────────────────────────────────────────────────────

def test_kpi_merges_sub_queries(monkeypatch):
    """kpi() merges four separate query() calls into one dict."""
    responses = [
        [{"cleanest_hour": "2024-01-01T06:00:00", "renewable_pct": 72.1, "avg_7d": 48.3}],
        [{"avg_demand_gw": 31.2, "peak_demand_gw": 38.9}],
        [{"avg_carbon": 187}],
        [{"stress_hours": 3}],
        [{"current_price_p_kwh": 14.22}],
    ]
    _patch_seq(monkeypatch, responses)
    r = client.get("/api/kpi")
    assert r.status_code == 200
    data = r.json()
    assert data["renewable_pct"] == 72.1
    assert data["avg_demand_gw"] == 31.2
    assert data["avg_carbon"] == 187
    assert data["stress_hours"] == 3
    assert data["current_price_p_kwh"] == 14.22
