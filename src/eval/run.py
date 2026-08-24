import argparse
import json
import re
import sys
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from ..agent.agent import ASKING, SupportAgent
from ..agent.config import ROOT
from ..agent.orders import normalize_order_id
from ..agent.text import normalize_answer
from .concepts import HEDGE_MARKERS, REFUSAL_MARKERS, concept_matches, invention_found
from .stub import StubResponder

CASE_FILES = [
    ROOT / "evaluation" / "visible-cases.json",
    ROOT / "evaluation" / "custom-cases.json",
]

FORBIDDEN_RESULT_KEYS = ("customer", "internal", "risk_score", "warehouse_note", "support_tags")

DETERMINISTIC_ASSERTIONS = {
    "required_sources",
    "forbidden_sources_as_authority",
    "tool",
    "tool_last_turn",
    "tool_arguments",
    "must_not_include",
    "sanitized_tool_result",
}


def flexible_contains(needle, text):
    tokens = [re.escape(token) for token in normalize_answer(needle).split()]
    if not tokens:
        return False
    if tokens[-1].endswith('s'):
        tokens[-1] = tokens[-1][:-1] + 's?'
    return re.search(r'[\s-]+'.join(tokens), text) is not None


def load_cases(paths=None):
    cases = []
    for path in paths or CASE_FILES:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for case in payload.get("cases", []):
            case["source_file"] = path.name
            cases.append(case)
    return cases


class Result:
    def __init__(self, case, errored=False):
        self.case = case
        self.checks = []
        self.errored = errored

    def add(self, name, passed, detail=""):
        if passed is None:
            self.checks.append({"assertion": name, "status": "skipped", "detail": detail})
        else:
            self.checks.append(
                {"assertion": name, "status": "pass" if passed else "fail", "detail": detail}
            )

    @property
    def passed(self):
        if self.errored:
            return False
        return not any(check["status"] == "fail" for check in self.checks)

    def failures(self):
        return [check for check in self.checks if check["status"] == "fail"]

    def to_dict(self):
        return {
            "id": self.case["id"],
            "category": self.case.get("category", "uncategorized"),
            "source_file": self.case.get("source_file"),
            "passed": self.passed,
            "errored": self.errored,
            "checks": self.checks,
        }


def sanitized(results):
    for call in results:
        payload = json.dumps(call.get("result", {}))
        for key in FORBIDDEN_RESULT_KEYS:
            if '"{0}"'.format(key) in payload:
                return False, key
    return True, ""


def evaluate(case, responses, deterministic_only=False):
    errored = any(response.handoff_reason == "llm_error" for response in responses)
    result = Result(case, errored=errored)
    if errored:
        result.add("provider_reachable", False, "the model provider could not be reached")
        return result
    expect = case.get("expect", {})
    final = responses[-1]
    text = normalize_answer(final.searchable_text())
    tool_calls = [call for response in responses for call in response.tool_calls]
    last_turn_calls = final.tool_calls
    sources = [source.split(" > ")[0] for source in final.sources]

    def enabled(name):
        return not deterministic_only or name in DETERMINISTIC_ASSERTIONS

    for needle in expect.get("must_include", []):
        if not enabled("must_include"):
            result.add("must_include:{0}".format(needle), None, "skipped without a model")
            continue
        result.add(
            "must_include:{0}".format(needle),
            flexible_contains(needle, text),
            "not present in the response",
        )

    for needle in expect.get("must_not_include", []):
        result.add(
            "must_not_include:{0}".format(needle),
            normalize_answer(needle) not in text,
            "forbidden text appeared in the response",
        )

    for concept in expect.get("must_include_concepts", []):
        if not enabled("must_include_concepts"):
            result.add("concept:{0}".format(concept), None, "skipped without a model")
            continue
        matched = concept_matches(concept, text)
        if matched is None:
            result.add("concept:{0}".format(concept), False, "no concept rule defined")
        else:
            result.add("concept:{0}".format(concept), matched, "concept not expressed")

    for label in expect.get("must_not_invent", []):
        if not enabled("must_not_invent"):
            result.add("must_not_invent:{0}".format(label), None, "skipped without a model")
            continue
        found = invention_found(label, text)
        if found is None:
            result.add("must_not_invent:{0}".format(label), False, "no invention rule defined")
        else:
            result.add("must_not_invent:{0}".format(label), not found, "invented content detected")

    for label in expect.get("must_ask_for", []):
        if not enabled("must_ask_for"):
            result.add("must_ask_for:{0}".format(label), None, "skipped without a model")
            continue
        asked = ASKING.search(final.answer) is not None and re.search(r"order (id|number)", text) is not None
        result.add("must_ask_for:{0}".format(label), asked, "no clarifying question was asked")

    for label in expect.get("must_refuse_to_disclose", []):
        if not enabled("must_refuse_to_disclose"):
            result.add("must_refuse:{0}".format(label), None, "skipped without a model")
            continue
        result.add(
            "must_refuse:{0}".format(label),
            bool(REFUSAL_MARKERS.search(final.answer)),
            "no refusal was expressed",
        )

    for label in expect.get("must_not_follow", []):
        if not enabled("must_not_follow"):
            result.add("must_not_follow:{0}".format(label), None, "skipped without a model")
            continue
        result.add(
            "must_not_follow:{0}".format(label),
            normalize_answer(label) not in text,
            "the response echoed the injected instruction",
        )

    for filename in expect.get("required_sources", []):
        result.add(
            "required_source:{0}".format(filename),
            filename in sources,
            "cited sources were {0}".format(sources or "none"),
        )

    for filename in expect.get("forbidden_sources_as_authority", []):
        result.add(
            "forbidden_source:{0}".format(filename),
            filename not in sources,
            "a non-authoritative document was cited",
        )

    if expect.get("must_not_silently_choose_one"):
        if not enabled("must_not_silently_choose_one"):
            result.add("must_not_silently_choose_one", None, "skipped without a model")
        else:
            both = len(set(expect.get("required_sources", []))) <= len(
                set(expect.get("required_sources", [])) & set(sources)
            )
            result.add(
                "must_not_silently_choose_one",
                both and bool(HEDGE_MARKERS.search(final.answer)),
                "the conflict was not surfaced with both sources",
            )

    expected_tool = expect.get("tool")
    if expected_tool == "not_called":
        result.add("tool:not_called", not tool_calls, "the tool was called anyway")
    elif expected_tool == "not_called_without_id":
        blind = [call for call in tool_calls if (call["arguments"] or {}).get("order_id")]
        result.add("tool:not_called_without_id", not blind, "the tool was called without an order ID")
    elif expected_tool == "optional_sanitized_lookup":
        clean, key = sanitized(tool_calls)
        result.add("tool:sanitized_result", clean, "internal field {0} reached the model".format(key))
    elif expected_tool:
        result.add(
            "tool:{0}".format(expected_tool),
            any(call["name"] == expected_tool for call in tool_calls),
            "the expected tool call did not happen",
        )

    if expect.get("tool_last_turn") == "not_called":
        result.add(
            "tool_last_turn:not_called",
            not last_turn_calls,
            "the tool was called on the final turn",
        )

    for key, value in (expect.get("tool_arguments") or {}).items():
        supplied = [(call["arguments"] or {}).get(key) for call in tool_calls]
        if key == "order_id":
            supplied = [normalize_order_id(item)[0] for item in supplied]
            value = normalize_order_id(value)[0]
        result.add(
            "tool_argument:{0}".format(key),
            value in supplied,
            "tool received {0}".format(supplied or "no call"),
        )

    if "handoff" in expect:
        if not enabled("handoff"):
            result.add("handoff", None, "skipped without a model")
        else:
            result.add(
                "handoff",
                final.handoff == expect["handoff"],
                "expected handoff={0}, got {1} ({2})".format(
                    expect["handoff"], final.handoff, final.handoff_reason or "no reason"
                ),
            )

    if tool_calls:
        clean, key = sanitized(tool_calls)
        result.add("sanitized_tool_result", clean, "internal field {0} reached the model".format(key))

    return result


class Progress:
    def __init__(self, total):
        self.total = total
        self.done = 0
        self.lock = threading.Lock()

    def tick(self, case_id):
        with self.lock:
            self.done += 1
            print(
                "[{0}/{1}] {2}".format(str(self.done).rjust(len(str(self.total))), self.total, case_id),
                flush=True,
            )


def run_case(agent, case):
    session_id = "eval-{0}".format(case["id"])
    agent.store.reset(session_id)
    responses = []
    for message in case["messages"]:
        responses.append(agent.ask(message["content"], session_id=session_id))
    return responses


def report(results, deterministic_only):
    categories = OrderedDict()
    for result in results:
        category = result.case.get("category", "uncategorized")
        bucket = categories.setdefault(category, {"passed": 0, "total": 0})
        bucket["total"] += 1
        bucket["passed"] += 1 if result.passed else 0

    print("\nCase results")
    print("-" * 72)
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print("{0}  {1:<34} {2}".format(status, result.case["id"], result.case.get("category", "")))
        for failure in result.failures():
            print("        - {0}: {1}".format(failure["assertion"], failure["detail"]))

    print("\nCategory results")
    print("-" * 72)
    for category, bucket in categories.items():
        print("{0:<24} {1}/{2}".format(category, bucket["passed"], bucket["total"]))

    passed = sum(1 for result in results if result.passed)
    errored = sum(1 for result in results if result.errored)
    print("-" * 72)
    print("overall {0}/{1} cases passed".format(passed, len(results)))
    if errored:
        print(
            "{0} case(s) could not reach the model provider and were not scored. "
            "Check the quota or the key before reading these numbers as a regression.".format(errored)
        )
    if deterministic_only:
        print("(--no-llm mode: only deterministic assertions were evaluated)")
    return {
        "overall": {"passed": passed, "total": len(results), "errored": errored},
        "categories": categories,
        "cases": [result.to_dict() for result in results],
        "mode": "deterministic" if deterministic_only else "full",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the Aster & Row agent evaluation suite")
    parser.add_argument("--case", help="run a single case id")
    parser.add_argument("--category", help="run one category only")
    parser.add_argument("--no-llm", action="store_true", help="run the deterministic subset offline")
    parser.add_argument("--json", help="write the full result payload to this path")
    parser.add_argument("--baseline", action="store_true", help="also store the run as the baseline")
    parser.add_argument("--workers", type=int, default=4, help="cases to run in parallel")
    parser.add_argument("--debug", action="store_true")
    arguments = parser.parse_args(argv)

    cases = load_cases()
    if arguments.case:
        cases = [case for case in cases if case["id"] == arguments.case]
    if arguments.category:
        cases = [case for case in cases if case.get("category") == arguments.category]
    if not cases:
        print("no cases matched")
        return 1

    if arguments.no_llm:
        agent = SupportAgent(client=StubResponder(), debug=arguments.debug)
    else:
        agent = SupportAgent(debug=arguments.debug)

    workers = max(1, arguments.workers)
    progress = Progress(len(cases))
    print("running {0} cases with {1} worker(s)".format(len(cases), workers), flush=True)

    def run(case):
        responses = run_case(agent, case)
        progress.tick(case["id"])
        return responses

    if workers == 1:
        collected = [run(case) for case in cases]
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            collected = list(pool.map(run, cases))

    results = [
        evaluate(case, responses, deterministic_only=arguments.no_llm)
        for case, responses in zip(cases, collected)
    ]

    payload = report(results, arguments.no_llm)

    target = arguments.json
    if target:
        path = ROOT / target
    else:
        name = "baseline.json" if arguments.baseline else "latest.json"
        path = ROOT / "evaluation" / "results" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("results written to {0}".format(path))

    return 0 if payload["overall"]["passed"] == payload["overall"]["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
