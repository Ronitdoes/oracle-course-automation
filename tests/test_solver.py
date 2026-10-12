"""Solver + validation unit tests (mocked, no API calls)."""
import asyncio
import json

import pytest

from solver.base import validate_candidate
from solver.llm_solver import MockSolver
from solver.schemas import (AnswerCandidate, AnswerOption, AnswerStatus,
                            Question, QuestionType)


def _q(**kw):
    base = dict(question_id="q1", text="What is 2 + 2?",
                options=[AnswerOption(option_id="a", text="3"),
                         AnswerOption(option_id="b", text="4")],
                question_type=QuestionType.SINGLE_SELECT, page_url="http://t")
    base.update(kw)
    return Question(**base)


async def _solve(q):
    return await MockSolver(mode="auto").solve(q)


def test_mock_solves_known_question():
    import asyncio
    cand = asyncio.run(_solve(_q()))
    assert cand.status == AnswerStatus.ANSWERED
    assert cand.selected_option_id == "b"


def test_mock_solves_all_fixture_questions():
    """Regression: mock solver must answer every fixture question correctly."""
    import asyncio

    async def go():
        s = MockSolver(mode="auto")
        cases = [
            (Question(question_id="q1", text="Q1: What is 2 + 2?",
                      options=[AnswerOption(option_id="a", text="3"),
                               AnswerOption(option_id="b", text="4"),
                               AnswerOption(option_id="c", text="5")],
                      question_type=QuestionType.SINGLE_SELECT), "b"),
            (Question(question_id="q2", text="Q2: What is the capital of France?",
                      options=[AnswerOption(option_id="paris", text="Paris"),
                               AnswerOption(option_id="london", text="London")],
                      question_type=QuestionType.SINGLE_SELECT), "paris"),
            (Question(question_id="q4-delayed", text="Q4 (delayed): Which is the largest planet?",
                      options=[AnswerOption(option_id="jupiter", text="Jupiter"),
                               AnswerOption(option_id="mars", text="Mars")],
                      question_type=QuestionType.SINGLE_SELECT), "jupiter"),
            (Question(question_id="q5", text="Q5: What is 10 - 3?",
                      options=[AnswerOption(option_id="a", text="6"),
                               AnswerOption(option_id="b", text="7"),
                               AnswerOption(option_id="c", text="8")],
                      question_type=QuestionType.SINGLE_SELECT), "b"),
        ]
        for q, want in cases:
            cand = await s.solve(q)
            assert cand.selected_option_id == want, (q.question_id, cand)
            ok, reason = validate_candidate(q, cand)
            assert ok, reason
        text_q = Question(question_id="q3", text="Q3: Type the word python (text entry).",
                          options=[], question_type=QuestionType.TEXT_ENTRY)
        cand = await s.solve(text_q)
        assert (cand.text_answer or "").strip().lower() == "python"
    asyncio.run(go())


def test_structured_response_validation_ok():
    q = _q()
    c = AnswerCandidate(selected_option_id="a", confidence=0.9)
    ok, reason = validate_candidate(q, c)
    assert ok, reason


def test_invalid_option_rejected():
    q = _q()
    c = AnswerCandidate(selected_option_id="zzz")
    ok, reason = validate_candidate(q, c)
    assert not ok
    assert "zzz" in reason


def test_unresolved_rejected():
    q = _q()
    c = AnswerCandidate(status=AnswerStatus.UNRESOLVED)
    ok, _ = validate_candidate(q, c)
    assert not ok


def test_text_entry_requires_text():
    q = _q(question_type=QuestionType.TEXT_ENTRY, options=[], text="Type the word python")
    ok, _ = validate_candidate(q, AnswerCandidate(text_answer="python"))
    assert ok
    bad, _ = validate_candidate(q, AnswerCandidate(text_answer="  "))
    assert not bad


def test_mock_unresolved_mode():
    import asyncio
    q = _q()
    cand = asyncio.run(MockSolver(mode="unresolved").solve(q))
    assert cand.status == AnswerStatus.UNRESOLVED
    ok, _ = validate_candidate(q, cand)
    assert not ok


def test_confidence_clamped():
    c = AnswerCandidate(selected_option_id="a", confidence=99.0)
    assert c.confidence == 1.0


def test_null_ids_tolerated():
    c = AnswerCandidate.model_validate({"selected_option_id": "b",
                                        "selected_option_ids": None,
                                        "status": "answered"})
    assert c.selected_option_id == "b"
    assert c.selected_option_ids == []


def test_build_solver_routes_gemini():
    from config import Settings
    from solver.llm_solver import GeminiSolver, build_solver

    s = Settings()
    s.llm_provider = "gemini"
    s.model_id = "gemini-3.5-flash-lite"
    assert isinstance(build_solver(s), GeminiSolver)


def test_build_solver_routes_groq_openai_compatible():
    from config import Settings
    from solver.llm_solver import GroqSolver, OpenAICompatibleSolver, build_solver

    s = Settings()
    s.llm_provider = "groq"
    s.model_id = "openai/gpt-oss-120b"
    s.api_key = "gsk-test"
    sol = build_solver(s)
    assert isinstance(sol, GroqSolver)
    assert isinstance(sol, OpenAICompatibleSolver)
    assert sol.DEFAULT_BASE_URL == "https://api.groq.com/openai/v1"


def test_settings_combine_api_keys(monkeypatch):
    from config import Settings

    monkeypatch.setenv("LLM_API_KEY", "k1")
    monkeypatch.setenv("LLM_API_KEYS", "k2, k1\nk3")
    s = Settings()
    assert s.api_keys == ["k1", "k2", "k3"]
    assert s.api_key == "k1"


def test_settings_plural_only_sets_primary(monkeypatch):
    from config import Settings

    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("LLM_API_KEYS", "k1;k2")
    s = Settings()
    assert s.api_keys == ["k1", "k2"]
    assert s.api_key == "k1"


def test_discover_ambiguous_tabs():
    import json
    import urllib.request

    from browser.session import AmbiguousTabs, _discover_url_via_cdp

    payload = json.dumps([
        {"type": "page", "url": "https://academy.oracle.com/pls/f?p=63000:190:111:::190:P190_ID:7795&cs=AAA"},
        {"type": "page", "url": "https://academy.oracle.com/pls/f?p=63000:190:222:::190:P190_ID:7807&cs=BBB"},
    ]).encode()

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return payload

    real = urllib.request.urlopen
    urllib.request.urlopen = lambda *a, **k: _Resp()
    try:
        with pytest.raises(AmbiguousTabs):
            _discover_url_via_cdp("http://localhost:9222", ["academy.oracle.com"])
    finally:
        urllib.request.urlopen = real


def test_discover_single_tab():
    import json
    import urllib.request

    from browser.session import _discover_url_via_cdp

    payload = json.dumps([
        {"type": "page", "url": "https://academy.oracle.com/pls/f?p=63000:190:AAA"},
    ]).encode()

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return payload

    real = urllib.request.urlopen
    urllib.request.urlopen = lambda *a, **k: _Resp()
    try:
        assert _discover_url_via_cdp("http://localhost:9222", ["academy.oracle.com"]) == \
            "https://academy.oracle.com/pls/f?p=63000:190:AAA"
    finally:
        urllib.request.urlopen = real


def test_discover_same_attempt_tabs_ok():
    import json
    import urllib.request

    from browser.session import _discover_url_via_cdp

    payload = json.dumps([
        {"type": "page", "url": "https://academy.oracle.com/pls/f?p=63000:190:111:::190::&cs=AAA"},
        {"type": "page", "url": "https://academy.oracle.com/pls/f?p=63000:190:222:::190::&cs=BBB"},
    ]).encode()

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return payload

    real = urllib.request.urlopen
    urllib.request.urlopen = lambda *a, **k: _Resp()
    try:
        # Same attempt (only session/cs differ) -> freshest tab, no raise.
        got = _discover_url_via_cdp("http://localhost:9222", ["academy.oracle.com"])
        assert got.endswith("cs=BBB"), got
    finally:
        urllib.request.urlopen = real


def _gemini_ok_payload(text: str = '{"selected_option_id": "b", "explanation": "4", "confidence": 0.9, "status": "answered"}'):
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}


def test_gemini_parse_valid():
    from solver.llm_solver import parse_gemini_response

    cand = parse_gemini_response(_gemini_ok_payload())
    assert cand.status == AnswerStatus.ANSWERED
    assert cand.selected_option_id == "b"


def test_gemini_parse_blocked_is_unresolved():
    from solver.llm_solver import parse_gemini_response

    cand = parse_gemini_response({"promptFeedback": {"blockReason": "SAFETY"}})
    assert cand.status == AnswerStatus.UNRESOLVED


def test_gemini_parse_bad_json_is_unresolved():
    from solver.llm_solver import parse_gemini_response

    cand = parse_gemini_response(_gemini_ok_payload("not json {{{"))
    assert cand.status == AnswerStatus.UNRESOLVED


def test_gemini_hallucinated_option_rejected():
    from solver.llm_solver import _check_option_grounding

    q = _q()
    cand = _check_option_grounding(q, AnswerCandidate(selected_option_id="zzz"))
    assert cand.status == AnswerStatus.UNRESOLVED


def test_adopt_text_match_exact():
    from solver.llm_solver import adopt_text_match

    q = _q()  # options a=3, b=4
    cand = adopt_text_match(q, AnswerCandidate(text_answer="4", status=AnswerStatus.ANSWERED))
    assert cand.selected_option_id == "b"
    assert cand.status == AnswerStatus.ANSWERED


def test_adopt_text_match_containment():
    from solver.llm_solver import adopt_text_match

    q = Question(question_id="q", text="t",
                 options=[AnswerOption(option_id="opt-0", text="A value of 10 would be displayed."),
                          AnswerOption(option_id="opt-1", text="A value of 0 would be displayed.")],
                 question_type=QuestionType.SINGLE_SELECT)
    cand = adopt_text_match(q, AnswerCandidate(
        text_answer="The answer is: A value of 0 would be displayed.", status=AnswerStatus.ANSWERED))
    assert cand.selected_option_id == "opt-1"


def test_adopt_text_match_no_match_stays_unusable():
    from solver.llm_solver import adopt_text_match, _check_option_grounding

    q = _q()
    cand = adopt_text_match(q, AnswerCandidate(text_answer="something unrelated", status=AnswerStatus.ANSWERED))
    assert cand.selected_option_id is None
    # ...and validation still rejects it downstream
    ok, _ = validate_candidate(q, cand)
    assert not ok


def test_adopt_respects_abstention():
    from solver.llm_solver import adopt_text_match

    q = _q()
    cand = adopt_text_match(q, AnswerCandidate(text_answer="4", status=AnswerStatus.UNRESOLVED))
    assert cand.status == AnswerStatus.UNRESOLVED
    assert cand.selected_option_id is None


def test_gemini_retries_once_on_abstention(monkeypatch):
    import httpx

    from config import Settings
    from solver.llm_solver import GeminiSolver

    calls = []

    def handler(request):
        calls.append(request)
        body = json.loads(request.content.decode())
        temp = body["generationConfig"]["temperature"]
        if temp == 0.0:
            text = '{"selected_option_id": null, "status": "unresolved", "explanation": "unsure"}'
        else:
            text = '{"selected_option_id": "b", "status": "answered", "explanation": "4", "confidence": 0.9}'
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(GeminiSolver, "_client",
                        lambda self: httpx.AsyncClient(transport=transport, base_url="http://test"))
    s = Settings()
    s.llm_provider = "gemini"
    s.model_id = "gemini-x"
    s.api_key = "k"
    solver = GeminiSolver(s)
    cand = asyncio.run(solver.solve(_q()))
    assert cand.selected_option_id == "b", cand
    assert solver.calls == 2
    assert len(calls) == 2


def test_gemini_double_abstention_stands(monkeypatch):
    import httpx

    from config import Settings
    from solver.llm_solver import GeminiSolver

    def handler(request):
        return httpx.Response(200, json={"candidates": [
            {"content": {"parts": [{"text": '{"status": "unresolved", "explanation": "no"}'}]}}]})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(GeminiSolver, "_client",
                        lambda self: httpx.AsyncClient(transport=transport, base_url="http://test"))
    s = Settings()
    s.llm_provider = "gemini"
    s.model_id = "gemini-x"
    s.api_key = "k"
    cand = asyncio.run(GeminiSolver(s).solve(_q()))
    assert cand.status == AnswerStatus.UNRESOLVED


def _openai_ok_response():
    import httpx

    return httpx.Response(200, json={"choices": [{"message": {"content":
        '{"selected_option_id": "b", "explanation": "4", "confidence": 0.9, "status": "answered"}'}}]})


def test_openai_failover_switches_key_and_sticks(monkeypatch):
    import httpx

    from config import Settings
    from solver.llm_solver import OpenAICompatibleSolver

    seen = []

    def handler(request):
        seen.append(request.headers.get("authorization"))
        if "bad-key" in (request.headers.get("authorization") or ""):
            return httpx.Response(401, json={"error": {"message": "Incorrect API key"}})
        return _openai_ok_response()

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(OpenAICompatibleSolver, "_client",
                        lambda self: httpx.AsyncClient(transport=transport, base_url="http://test"))
    s = Settings()
    s.llm_provider = "openai"
    s.model_id = "gpt-4o-mini"
    s.api_key = "bad-key"
    s.api_keys = ["bad-key", "good-key"]
    solver = OpenAICompatibleSolver(s)
    cand = asyncio.run(solver.solve(_q()))
    assert cand.selected_option_id == "b", cand
    assert solver.calls == 2  # 1 failed key + 1 working key
    # Sticky: next question starts with the working key (one call, no failure).
    cand2 = asyncio.run(solver.solve(_q()))
    assert cand2.selected_option_id == "b", cand2
    assert solver.calls == 3
    assert seen[-1] == "Bearer good-key"


def test_openai_all_keys_down_raises(monkeypatch):
    import httpx

    from config import Settings
    from solver.llm_solver import OpenAICompatibleSolver

    def handler(request):
        return httpx.Response(401, json={"error": {"message": "Incorrect API key"}})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(OpenAICompatibleSolver, "_client",
                        lambda self: httpx.AsyncClient(transport=transport, base_url="http://test"))
    s = Settings()
    s.llm_provider = "openai"
    s.model_id = "gpt-4o-mini"
    s.api_key = "bad-1"
    s.api_keys = ["bad-1", "bad-2"]
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(OpenAICompatibleSolver(s).solve(_q()))


def test_openai_non_key_error_does_not_burn_pool(monkeypatch):
    import httpx

    from config import Settings
    from solver.llm_solver import OpenAICompatibleSolver

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(404, json={"error": {"message": "model not found"}})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(OpenAICompatibleSolver, "_client",
                        lambda self: httpx.AsyncClient(transport=transport, base_url="http://test"))
    s = Settings()
    s.llm_provider = "openai"
    s.model_id = "nope"
    s.api_key = "k1"
    s.api_keys = ["k1", "k2"]
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(OpenAICompatibleSolver(s).solve(_q()))
    assert len(calls) == 1  # wrong model fails on every key: raise at once


def test_gemini_failover_switches_key(monkeypatch):
    import httpx

    from config import Settings
    from solver.llm_solver import GeminiSolver

    def handler(request):
        if "bad-key" in (request.headers.get("x-goog-api-key") or ""):
            return httpx.Response(429, json={"error": {"message": "quota exceeded"}})
        text = '{"selected_option_id": "b", "status": "answered", "explanation": "4", "confidence": 0.9}'
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(GeminiSolver, "_client",
                        lambda self: httpx.AsyncClient(transport=transport, base_url="http://test"))
    s = Settings()
    s.llm_provider = "gemini"
    s.model_id = "gemini-3.5-flash-lite"
    s.api_key = "bad-key"
    s.api_keys = ["bad-key", "good-key"]
    solver = GeminiSolver(s)
    cand = asyncio.run(solver.solve(_q()))
    assert cand.selected_option_id == "b", cand
