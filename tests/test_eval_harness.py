from src.agent.agent import AgentResponse
from src.eval.run import evaluate, flexible_contains, load_cases, sanitized
from src.agent.text import normalize_answer


def response(answer, sources=None, handoff=False, reason="", tool_calls=None):
    return AgentResponse(
        answer=answer,
        sources=sources or [],
        handoff=handoff,
        handoff_reason=reason,
        tool_calls=tool_calls or [],
    )


def test_every_supplied_case_is_loaded():
    ids = [case["id"] for case in load_cases()]
    assert "standard-return-window" in ids
    assert "genuine-active-source-conflict" in ids
    assert len(ids) == 23
    assert len(set(ids)) == len(ids)


def test_hyphenated_and_plural_forms_still_match():
    text = normalize_answer("You receive a 45-calendar-day return window from delivery.")
    assert flexible_contains("45 calendar days", text)
    assert not flexible_contains("60 calendar days", text)


def test_provider_failure_is_an_error_not_a_failed_assertion():
    case = {
        "id": "x",
        "category": "retrieval",
        "messages": [{"role": "user", "content": "hi"}],
        "expect": {"must_include": ["30 calendar days"], "handoff": False},
    }
    result = evaluate(case, [response("internal error", handoff=True, reason="llm_error")])
    assert result.errored is True
    assert result.passed is False
    assert [check["assertion"] for check in result.checks] == ["provider_reachable"]


def test_internal_fields_in_a_tool_result_are_caught():
    clean, key = sanitized([{"result": {"order_id": "ORD-1007", "status": "shipped"}}])
    assert clean is True
    dirty, key = sanitized([{"result": {"internal": {"risk_score": 82}}}])
    assert dirty is False
    assert key == "internal"


def test_required_source_checks_the_citation_list():
    case = {
        "id": "y",
        "category": "retrieval",
        "messages": [{"role": "user", "content": "hi"}],
        "expect": {
            "required_sources": ["01-returns-policy-current.md"],
            "forbidden_sources_as_authority": ["02-returns-policy-legacy.md"],
        },
    }
    good = evaluate(case, [response("x", sources=["01-returns-policy-current.md > Standard return window"])])
    assert good.passed is True
    bad = evaluate(case, [response("x", sources=["02-returns-policy-legacy.md > Return window"])])
    assert bad.passed is False
