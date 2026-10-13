"""Detection accuracy: metric maths, analyst-labelled metrics, and the synthetic benchmark as a regression guard."""
from app.services.evaluation import benchmark_metrics, summarize
from conftest import CSRF, signup, wait_for_scan
from test_api import create_brand


def test_metric_maths():
    m = summarize([("critical", 80, True), ("medium", 40, True), ("low", 30, False), ("medium", 45, False), ("low", 20, True)])
    med = m["by_threshold"]["medium"]
    assert (med["tp"], med["fp"], med["fn"], med["tn"]) == (2, 1, 1, 1)
    assert med["precision"] == round(2 / 3, 4) and med["recall"] == round(2 / 3, 4)
    assert m["labelled"] == 5 and m["positives"] == 3 and not m["enough_labels"]  # < 20 labels
    assert m["score_sweep"][0]["min_score"] == 0 and m["score_sweep"][-1]["min_score"] == 100


def test_benchmark_regression_guard():
    """Fails if a detection change makes the engine meaningfully worse on the hand-labelled set."""
    m = benchmark_metrics()
    assert m["official_assets_flagged"] == []  # official assets are always excluded
    med = m["by_threshold"]["medium"]
    assert med["precision"] >= 0.8 and med["recall"] >= 0.85, med
    assert m["by_threshold"]["critical"]["precision"] == 1.0  # critical is reserved for corroborated scams
    cases = {c["id"]: c for c in m["cases"]}
    assert all(cases[f"n{i:02d}"]["risk_level"] in ("low", "info") for i in range(1, 11))  # clear legitimate look-alikes stay low


def test_analyst_metrics_use_only_decisions_and_exclude_synthetic(authed):
    demo = authed.post("/api/demo/brand", headers=CSRF).json()
    wait_for_scan(authed, authed.post(f"/api/brands/{demo['id']}/scans", json={}, headers=CSRF).json()["id"])
    items = authed.get("/api/findings", params={"brand_id": demo["id"], "limit": 3}).json()["items"]
    authed.post(f"/api/findings/{items[0]['id']}/decision", json={"action": "confirm"}, headers=CSRF)
    m = authed.get("/api/evaluation").json()
    assert m["labelled"] == 0 and m["excluded_simulated"] == 1  # demo findings are synthetic: never used as ground truth
    assert "optimistic" in m["note"]


def test_evaluation_is_org_scoped(client):
    signup(client, org="Eval A")
    b = create_brand(client, name="Eval Brand")
    client.cookies.clear()
    signup(client, org="Eval B")
    assert client.get("/api/evaluation", params={"brand_id": b["id"]}).status_code == 404
    assert client.get("/api/evaluation/benchmark").status_code == 200
