"""What is sent to LightRAG and what the agent gets back."""
import asyncio
import datetime as dt
import json

import httpx

from app import lightrag
from app.config import Settings

KEY = "test-key-not-real-0123"


def run(coro):
    return asyncio.run(coro)


def answer(request):
    return httpx.Response(200, json={
        "response": "คำตอบจากคลัง",
        "references": [{"reference_id": "1", "file_path": "report-a"}, {"reference_id": "2", "file_path": "report-b"}],
    })


def test_query_sends_mode_key_and_extra_params(monkeypatch, fake_lightrag):
    monkeypatch.setenv("LIGHTRAG_API_KEY", KEY)
    monkeypatch.setenv("QUERY_EXTRA_PARAMS", '{"top_k": 40}')
    seen = fake_lightrag(answer)
    run(lightrag.query(Settings.from_env(), "ใครเป็นใคร", "mix"))
    req = seen[0]
    assert req.url == "http://lightrag:9621/query"
    assert req.headers["X-API-Key"] == KEY
    assert json.loads(req.content) == {"top_k": 40, "query": "ใครเป็นใคร", "mode": "mix", "stream": False}


def test_key_is_sent_on_every_call(fake_lightrag):
    seen = fake_lightrag(answer)
    run(lightrag.query(Settings.from_env(), "q", "hybrid"))
    assert seen[0].headers["X-API-Key"] == KEY


def test_answer_lists_its_references(fake_lightrag):
    fake_lightrag(answer)
    out = run(lightrag.query(Settings.from_env(), "q", "hybrid"))
    assert out == "คำตอบจากคลัง\n\nReferences:\n- [1] report-a\n- [2] report-b"


def test_references_already_in_the_answer_are_not_repeated():
    # the LLM cites only what it used; the other retrieved documents are not added back
    data = {"response": "คำตอบ\n\n### References\n- [1] report-a",
            "references": [{"reference_id": "1", "file_path": "report-a"}, {"reference_id": "2", "file_path": "report-b"}]}
    assert lightrag.format_answer(data) == data["response"]


def test_answer_without_references_is_just_the_text():
    assert lightrag.format_answer({"response": "ok", "references": []}) == "ok"
    assert lightrag.format_answer("plain") == "plain"
    assert lightrag.format_answer({"other": 1}) == '{"other": 1}'


def test_refused_key_is_explained(fake_lightrag):
    fake_lightrag(lambda r: httpx.Response(401, json={"detail": "Invalid API Key"}))
    out = run(lightrag.query(Settings.from_env(), "q", "hybrid"))
    assert out.startswith("[LightRAG error HTTP 401") and "LIGHTRAG_API_KEY" in out


def test_server_error_is_passed_on(fake_lightrag):
    fake_lightrag(lambda r: httpx.Response(500, text="boom"))
    out = run(lightrag.query(Settings.from_env(), "q", "hybrid"))
    assert out.startswith("[LightRAG error HTTP 500]") and "boom" in out


def test_unreachable_lightrag_names_the_url(fake_lightrag):
    def down(request):
        raise httpx.ConnectError("refused", request=request)

    fake_lightrag(down)
    out = run(lightrag.query(Settings.from_env(), "q", "hybrid"))
    assert "connection error" in out and "http://lightrag:9621" in out


def test_insert_sends_text_under_a_document_name(fake_lightrag):
    seen = fake_lightrag(lambda r: httpx.Response(200, json={"status": "success", "track_id": "t1"}))
    out = json.loads(run(lightrag.insert(Settings.from_env(), "เนื้อหา", "รายงาน ประจำเดือน/ตุลาคม")))
    assert seen[0].url == "http://lightrag:9621/documents/text"
    assert json.loads(seen[0].content) == {"text": "เนื้อหา", "file_source": "รายงาน-ประจำเดือน-ตุลาคม"}
    assert out == {"status": "success", "track_id": "t1", "file_source": "รายงาน-ประจำเดือน-ตุลาคม"}


def test_document_name_keeps_thai_marks_and_falls_back_to_a_timestamp():
    assert lightrag.document_name("สรุปข่าว ภูมิภาคเอเชีย") == "สรุปข่าว-ภูมิภาคเอเชีย"
    assert lightrag.document_name("  a:b*c?  ") == "a-b-c"
    assert lightrag.document_name("x" * 200) == "x" * 80
    assert lightrag.document_name("", dt.datetime(2026, 10, 19, 8, 5, 1)) == "insert-20261019-080501"


def fake_server(request):
    if request.url.path == "/health":
        return httpx.Response(200, json={"status": "healthy"})
    return httpx.Response(200 if request.headers.get("X-API-Key") == KEY else 401, json={})


def test_check_notices_a_refused_key(monkeypatch, fake_lightrag):
    monkeypatch.setenv("LIGHTRAG_API_KEY", "test-key-wrong")
    fake_lightrag(fake_server)
    assert run(lightrag.check(Settings.from_env())) == {"reachable": True, "key_accepted": False, "http_status": 200}


def test_check_with_the_right_key(monkeypatch, fake_lightrag):
    monkeypatch.setenv("LIGHTRAG_API_KEY", KEY)
    fake_lightrag(fake_server)
    assert run(lightrag.check(Settings.from_env()))["key_accepted"] is True
