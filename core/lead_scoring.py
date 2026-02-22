from __future__ import annotations

import re
from typing import Any


_DOMAIN_KWS = (
    "fda",
    "510(k)",
    "510k",
    "clearance",
    "cleared",
    "de novo",
    "pma",
    "ivd",
    "ldt",
    "samd",
    "pccp",
    "guidance",
    "draft guidance",
    "regulatory",
    "quality",
    "iso 13485",
    "21 cfr 820",
)

_SIGNAL_KWS = (
    "layoff",
    "layoffs",
    "departure",
    "stepped down",
    "hiring",
    "job posting",
    "funding",
    "series a",
    "series b",
    "acquired",
    "launch",
    "submission",
    "submitted",
    "seeking clearance",
)


def _text_blob(lead: dict[str, Any]) -> str:
    parts = [
        lead.get("company", ""),
        lead.get("name", ""),
        lead.get("title", ""),
        lead.get("rationale", ""),
        " ".join(lead.get("signals") or []),
    ]
    return " ".join([str(p) for p in parts if p]).lower()


def score_lead(lead: dict[str, Any]) -> dict[str, int]:
    """
    Heuristic scoring:
    - confidence_score: based on number of sources
    - signals_score: staffing/regulatory signals
    - fit_score: domain fit (MedTech/FDA/IVD/SaMD)
    """
    sources = lead.get("sources") or []
    if not isinstance(sources, list):
        sources = []

    blob = _text_blob(lead)
    # Confidence: 0..20
    confidence_score = min(20, len([s for s in sources if s]) * 4)

    # Fit: 0..20
    fit_hits = sum(1 for kw in _DOMAIN_KWS if kw in blob)
    fit_score = min(20, fit_hits * 3)

    # Signals: 0..30
    sig_hits = sum(1 for kw in _SIGNAL_KWS if kw in blob)
    # Extra bump if openFDA appears
    if "openfda 510" in blob or "510(k)" in blob or "510k" in blob:
        sig_hits += 1
    signals_score = min(30, sig_hits * 4)

    total = signals_score + fit_score + confidence_score
    return {
        "signals_score": int(signals_score),
        "fit_score": int(fit_score),
        "confidence_score": int(confidence_score),
        "total_score": int(total),
    }

