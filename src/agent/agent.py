import json
import re
from dataclasses import dataclass, field

from .config import settings
from .llm import LLMClient, LLMError
from .orders import order_lookup, tool_schema
from .prompts import SYSTEM_PROMPT, build_context_block, format_tool_result
from .retriever import Retriever, find_conflicts
from .session import SessionStore
from .text import tokenize
from .trace import Trace

HANDOFF_TOKEN = "[[HANDOFF]]"
CLARIFYING = re.compile(r"order (id|number)", re.IGNORECASE)
ASKING = re.compile(
    r"(\?|please (provide|share|confirm|send)|could you|can you|let me know|what is your)",
    re.IGNORECASE,
)

INSUFFICIENT = re.compile(
    r"(\binsufficient\b"
    r"|not (enough|sufficient)[^.]{0,24}(information|detail|to (answer|confirm|say|tell))"
    r"|(information|documentation|documents|passages) [^.]{0,24}(not (enough|sufficient)|do(es)? not"
    r" (contain|include|specify|cover))"
    r"|(cannot|can't|unable to) confirm"
    r"|(do not|don't) have (enough|that|this) information"
    r"|no information (about|on|regarding))",
    re.IGNORECASE,
)

CANNOT_ACT = re.compile(
    r"(cannot|can't|unable to|not able to) (cancel|refund|approve|issue|process|replace|exchange"
    r"|change|complete|adjust)",
    re.IGNORECASE,
)
SOURCES_LINE = re.compile(r"^\s*sources?\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)

PRIVACY_PROBE = re.compile(
    r"\b(system prompt|hidden (prompt|instruction)|internal note|warehouse note|risk score|"
    r"support tag|customer'?s? (email|address|name)|shipping address|credentials|api key)\b",
    re.IGNORECASE,
)

INJECTION_PREMISE = re.compile(
    r"(migration (note|scratchpad)|ignore (the|all) (real |current )?(policy|rules|instructions)|"
    r"use that (newer|other) document|internal note says|the document says to)",
    re.IGNORECASE,
)

ACTION_REQUEST = re.compile(
    r"\b(cancel|refund|replace|replacement|exchange|return it|approve|approval|price adjustment"
    r"|change (my|the) address|issue (me|a)|credit me|give me the difference|reship|resend)\b"
    r"|\b(arrived|came|showed up)\b[^.]{0,40}\b(damaged|broken|defective|wrong|cracked|torn)\b"
    r"|\b(damaged|broken|defective|wrong|faulty)\b[^.]{0,40}\b(item|bag|zipper|order|tumbler|product)\b",
    re.IGNORECASE,
)

FALLBACK_MESSAGE = (
    "I could not complete that request because the support assistant hit an internal error. "
    "Please try again, or contact the Aster & Row support team so a specialist can help."
)


@dataclass
class AgentResponse:
    answer: str
    sources: list = field(default_factory=list)
    handoff: bool = False
    handoff_reason: str = ""
    tool_calls: list = field(default_factory=list)
    retrieved: list = field(default_factory=list)
    trace: dict = field(default_factory=dict)

    def display(self):
        parts = [self.answer]
        if self.sources:
            parts.append("Sources: " + ", ".join(self.sources))
        if self.handoff:
            parts.append("Recommended next step: a human support specialist should take this over.")
        return "\n\n".join(parts)

    def searchable_text(self):
        return "\n".join([self.answer] + self.sources)


class SupportAgent:
    def __init__(self, client=None, retriever=None, store=None, debug=False):
        self.client = client or LLMClient()
        self.retriever = retriever or Retriever()
        self.store = store or SessionStore()
        self.debug = debug

    def ask(self, message, session_id="cli"):
        session = self.store.get(session_id)
        trace = Trace(session_id, message, echo=self.debug)
        query, rewritten = session.contextualize(message)
        history = session.history()
        session.add_user(message)

        passages = self.retriever.retrieve(query)
        conflicts = find_conflicts(passages, self.retriever._word_idf)
        facts = session.facts(message)

        trace.set("history", history)
        trace.set(
            "retrieval",
            {
                "query": query,
                "rewritten_from_history": rewritten,
                "conflicts": conflicts,
                "passages": [item.to_trace() for item in passages],
            },
        )
        trace.set("session_facts", facts)

        context = build_context_block(message, passages, conflicts, facts)
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for turn in history:
            messages.append(turn)
        messages.append({"role": "user", "content": context})

        try:
            answer, tool_calls = self._run(messages, trace, session)
        except LLMError as error:
            trace.event("llm_error", error=str(error))
            session.add_assistant(FALLBACK_MESSAGE)
            record = trace.finish(FALLBACK_MESSAGE, [], True, "llm_error")
            return AgentResponse(
                answer=FALLBACK_MESSAGE,
                handoff=True,
                handoff_reason="llm_error",
                retrieved=passages,
                trace=record,
            )

        model_handoff = HANDOFF_TOKEN in answer
        answer = answer.replace(HANDOFF_TOKEN, "").strip()
        sources = self._resolve_sources(answer, passages)
        answer = SOURCES_LINE.sub("", answer).strip()

        handoff, reason = self._decide_handoff(
            message, answer, passages, conflicts, tool_calls, model_handoff
        )
        session.add_assistant(answer)
        record = trace.finish(answer, sources, handoff, reason)

        return AgentResponse(
            answer=answer,
            sources=sources,
            handoff=handoff,
            handoff_reason=reason,
            tool_calls=tool_calls,
            retrieved=passages,
            trace=record,
        )

    def _run(self, messages, trace, session):
        tool_calls = []
        for _ in range(settings.max_tool_calls + 1):
            message = self.client.complete(messages, tools=[tool_schema()])
            requested = getattr(message, "tool_calls", None)
            if not requested:
                return (message.content or "").strip(), tool_calls
            messages.append(self._as_message(message, requested))
            for call in requested:
                arguments = self._parse_arguments(call.function.arguments)
                if call.function.name != "order_lookup":
                    result = {"error": "unknown tool"}
                else:
                    result = order_lookup(arguments.get("order_id"))
                    if result.get("found"):
                        session.note_order(result["order_id"])
                tool_calls.append({"name": call.function.name, "arguments": arguments, "result": result})
                trace.tool_call(call.function.name, arguments, result)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": format_tool_result(result),
                    }
                )
        trace.event("tool_loop_limit")
        return (
            "I could not finish looking that up. Please contact the Aster & Row support team "
            "so a specialist can check it for you.",
            tool_calls,
        )

    def _as_message(self, message, requested):
        if hasattr(message, "model_dump"):
            payload = message.model_dump(exclude_none=True)
            payload["role"] = "assistant"
            payload.setdefault("content", message.content or "")
            return payload
        return {
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in requested
            ],
        }

    def _parse_arguments(self, raw):
        try:
            return json.loads(raw) if isinstance(raw, str) else dict(raw or {})
        except (ValueError, TypeError):
            return {"order_id": None}

    def _resolve_sources(self, answer, passages):
        allowed = {item.chunk.citation.lower(): item.chunk.citation for item in passages if item.citable}
        declared = []
        for match in SOURCES_LINE.findall(answer):
            for part in match.split(","):
                cleaned = part.strip().strip(".").replace("›", ">").replace("|", ">")
                cleaned = re.sub(r"\s*>\s*", " > ", cleaned)
                key = cleaned.lower()
                if key in allowed and allowed[key] not in declared:
                    declared.append(allowed[key])
        inferred = [item for item in self._infer_sources(answer, passages) if item not in declared]
        return (declared + inferred)[:4]

    def _infer_sources(self, answer, passages):
        answer_tokens = set(tokenize(answer))
        inferred = []
        for item in passages:
            if not item.citable:
                continue
            distinctive = {
                token
                for token in tokenize(item.text)
                if self.retriever._word_idf.get(token, 0) > 1.2
            }
            if len(distinctive & answer_tokens) >= 4:
                inferred.append(item.chunk.citation)
            if len(inferred) >= 3:
                break
        return inferred

    def _decide_handoff(self, message, answer, passages, conflicts, tool_calls, model_handoff):
        if conflicts:
            return True, "authoritative_sources_conflict"
        for call in tool_calls:
            result = call.get("result", {})
            if result.get("found") is False:
                return True, "order_lookup_failed"
            if result.get("requires_human"):
                return True, "order_requires_review"
        if PRIVACY_PROBE.search(message):
            return True, "internal_data_requested"
        if not passages and not tool_calls:
            return True, "no_supporting_content"
        if INJECTION_PREMISE.search(message):
            return False, "premise_correction_only"
        if not tool_calls and CLARIFYING.search(answer) and ASKING.search(answer):
            return False, "clarifying_question_only"
        if model_handoff:
            if not ACTION_REQUEST.search(message) and not INSUFFICIENT.search(answer):
                return False, "policy_answer_only"
            return True, "model_requested_human_help"
        if INSUFFICIENT.search(answer):
            return True, "insufficient_information"
        if CANNOT_ACT.search(answer):
            return True, "action_requires_specialist"
        return False, ""
