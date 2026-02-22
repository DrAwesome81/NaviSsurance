import types
from unittest.mock import patch


def test_openfda_510k_parsing_and_summary():
    from core.openfda import search_510k_by_applicant, summarize_510k_records

    fake_payload = {
        "meta": {"results": {"total": 1}},
        "results": [
            {
                "k_number": "K123456",
                "applicant": "Example Co",
                "device_name": "Widget",
                "date_received": "2024-01-02",
                "decision_date": "2024-06-07",
                "decision_description": "SESE",
                "contact": "Example Regulatory Consulting, LLC",
            }
        ],
    }

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return fake_payload

    with patch("core.openfda.requests.get", return_value=_Resp()) as m:
        recs, req_url = search_510k_by_applicant("Example Co", limit=5)
        assert req_url.startswith("https://api.fda.gov/device/510k.json?")
        assert len(recs) == 1
        assert recs[0].k_number == "K123456"

        summ = summarize_510k_records("Example Co", recs, req_url)
        assert "signals" in summ and "sources" in summ and "meta" in summ
        assert summ["meta"]["matches"] == 1
        assert any("openFDA 510(k)" in s for s in summ["signals"])
        assert any("external" in s.lower() for s in summ["signals"])
        assert req_url in summ["sources"]

