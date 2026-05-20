from core.compliance import ComplianceChecker, _parse_compliance_json_response
# Compliance checker tests validate Pulse [Security-Relevant] intel loading and Shield triage in assessments (compliance pillar tests)


def test_check_compliance_delegates_to_run_method(monkeypatch):
    checker = ComplianceChecker(chat_handler=None)
    called = {}

    def _run(ref_items, assess_items, session_id, conversation_history):
        called["args"] = (ref_items, assess_items, session_id, conversation_history)
        return {"success": True, "data": {"improvements": []}}

    monkeypatch.setattr(checker, "run_compliance_check", _run)

    result = checker.check_compliance(
        ["ref.pdf"],
        ["assess.pdf"],
        "compliance_session",
        [{"role": "user", "content": "check this"}],
    )

    assert called["args"] == (
        ["ref.pdf"],
        ["assess.pdf"],
        "compliance_session",
        [{"role": "user", "content": "check this"}],
    )
    assert result == {"success": True, "data": {"improvements": []}}


def test_run_compliance_check_uses_generic_file_extractor(monkeypatch, tmp_path):
    docx_path = tmp_path / "sop.docx"
    docx_path.write_text("placeholder", encoding="utf-8")

    extracted_paths = []

    def _extract(path):
        extracted_paths.append(path)
        return "SOP body text"

    class _ChatHandler:
        def get_response(self, prompt, session_id, conversation_history):
            assert "Reference Documents:" in prompt
            assert "SOP body text" in prompt
            return '{"overview":"ok","key_alignments":"aligned","improvements":[],"recommendations":"done"}'

    class _Resp:
        text = "<html><body><h1>Reference</h1><p>Reference body text</p></body></html>"

        def raise_for_status(self):
            return None

    monkeypatch.setattr("core.compliance.requests.get", lambda *args, **kwargs: _Resp())
    monkeypatch.setattr("core.compliance.extract_text_from_file", _extract)

    checker = ComplianceChecker(chat_handler=_ChatHandler())
    result = checker.run_compliance_check(
        ["https://example.com/ref"],
        [str(docx_path)],
        "compliance_session",
        [],
    )

    assert extracted_paths == [str(docx_path)]
    assert result["success"] is True
    assert result["data"]["overview"] == "ok"


def test_request_analysis_prefers_grok_before_chat_handler(monkeypatch):
    calls = {"grok": 0, "chat": 0}

    class _ChatHandler:
        def get_response(self, prompt, session_id, conversation_history):
            calls["chat"] += 1
            return "chat fallback"

    def _grok_available():
        return True, ""

    def _grok_completion(system, user, model):
        calls["grok"] += 1
        return '{"overview":"ok","key_alignments":"","improvements":[],"recommendations":""}'

    monkeypatch.setattr("core.compliance.grok_available", _grok_available)
    monkeypatch.setattr("core.compliance.grok_completion", _grok_completion)

    checker = ComplianceChecker(chat_handler=_ChatHandler())
    out = checker._request_analysis("prompt", "compliance_session", [])

    assert calls["grok"] == 1
    assert calls["chat"] == 0
    assert '"overview":"ok"' in out


def test_parse_compliance_json_repairs_split_key_alignments_strings():
    raw = (
        '{"overview":"ok",'
        '"key_alignments":"- item 1","- item 2","- item 3",'
        '"improvements":[{"section":"S1","issue":"I1","fix":"F1","reference":"R1"}],'
        '"recommendations":"done"}'
    )

    parsed = _parse_compliance_json_response(raw)

    assert parsed["overview"] == "ok"
    assert parsed["key_alignments"] == "- item 1\n- item 2\n- item 3"
    assert parsed["improvements"][0]["section"] == "S1"

# Pulse private memory + Shield triage in compliance test surface
