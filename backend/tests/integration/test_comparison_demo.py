"""The delivered synthetic PDFs must work through the real upload API."""

from decimal import Decimal
from pathlib import Path

from tests.integration.test_benchmarks_and_challenges import bench_client  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
DEMO = ROOT / "output/pdf/benchmark-comparison-demo"


def test_demo_uploads_are_separate_and_all_three_new_invoices_can_draft(bench_client):  # noqa: F811
    c = bench_client
    ref = "COMPARISON-DEMO-QA"
    assert (
        c.post(
            "/api/v1/claims",
            json={"case_reference": ref, "claim_number": "SYNTHETIC-DEMO", "created_by": "demo.qa"},
        ).status_code
        == 201
    )
    baseline = {}
    for folder, group, source in [
        ("01-third-party", "historical_claim", "third_party"),
        ("02-in-house", "in_house", "aviva_dlg"),
        ("03-new-invoices", "live", None),
    ]:
        files = [
            (slot, (p.name, p.read_bytes(), "application/pdf"))
            for directory, slot in [
                ("invoices", "invoice_files"),
                ("assessments", "estimate_files"),
            ]
            for p in sorted((DEMO / folder / directory).glob("*.pdf"))
        ]
        assert len(files) == 6
        r = c.post(
            f"/api/v1/claims/{ref}/documents/batch", files=files, data={"intake_group": group}
        )
        assert r.status_code == 200, r.text
        assert (r.json()["accepted"], r.json()["failed"]) == (6, 0), r.text
        mapping = c.get(
            f"/api/v1/claims/{ref}/document-mapping", params={"intake_group": group}
        ).json()
        approval = c.post(
            f"/api/v1/claims/{ref}/document-mapping/approve",
            json={"actor": "demo.qa", "intake_group": group},
        )
        assert approval.status_code == 200, (approval.text, mapping)
        if source:
            b = c.get(f"/api/v1/claims/{ref}/benchmarks", params={"source": source}).json()
            assert b["invoice_count"] == 3
            assert len(b["rows"]) == 3
            assert all(row["observations"] == 3 for row in b["rows"])
            baseline[source] = b
    for source, b in baseline.items():
        assert c.get(f"/api/v1/claims/{ref}/benchmarks", params={"source": source}).json() == b, (
            "Other sources changed this population"
        )
    live = c.get(f"/api/v1/claims/{ref}/benchmark-analysis").json()["live_invoices"]
    assert len(live) == 3
    expected = {"DEMO-NEW-001": "58.80", "DEMO-NEW-002": "78.00", "DEMO-NEW-003": "93.00"}
    for invoice in live:
        a = c.get(
            f"/api/v1/claims/{ref}/benchmark-analysis", params={"invoice_id": invoice["id"]}
        ).json()
        assert a["invoice"]["paired_assessment_number"] == invoice["invoice_number"].replace(
            "DEMO-", "EA-"
        )
        assert len(a["lines"]) == 3
        door = next(line for line in a["lines"] if line["description"] == "L/R DOOR")
        assert door["benchmarks"]["third_party"]["p90"] == "118.00"
        assert door["benchmarks"]["aviva_dlg"]["p90"] == "98.00"
        assert door["challenge"]["justified_amount"] == "108.00"
        assert a["totals"]["total_challenge_amount"] == expected[invoice["invoice_number"]]
        chosen = [line["line_id"] for line in a["lines"] if line["challenge"]["is_challenge"]]
        r = c.post(
            f"/api/v1/claims/{ref}/challenge-email",
            json={"invoice_id": invoice["id"], "line_ids": chosen, "recipient": "Demo repairer"},
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["total_challenge_amount"] == expected[invoice["invoice_number"]]
        assert "50%" in d["body"] and "EXL/in-house" in d["body"]
        assert "Aviva" not in d["body"]
        assert Decimal(d["total_challenge_amount"]) > 0
