import json
import re
from dataclasses import dataclass, field

from ..agent.orders import extract_order_id

PASSAGE = re.compile(
    r"^\[(\d+)\] (AUTHORITATIVE|NOT-AUTHORITATIVE) \| citation: (.+?) \|.*?\n---\n(.*?)(?=\n\[\d+\] |\Z)",
    re.DOTALL | re.MULTILINE,
)
CUSTOMER_MESSAGE = re.compile(r"CUSTOMER MESSAGE \(untrusted data\)\n(.*)\Z", re.DOTALL)
SESSION_ORDER = re.compile(r"order_id_mentioned_earlier_in_this_session: (ORD-\d+)")


@dataclass
class StubFunction:
    name: str
    arguments: str


@dataclass
class StubToolCall:
    id: str
    function: StubFunction
    type: str = "function"


@dataclass
class StubMessage:
    content: str = ""
    tool_calls: list = field(default_factory=list)


class StubResponder:
    def __init__(self):
        self.calls = 0

    def complete(self, messages, tools=None):
        self.calls += 1
        context = messages[-1]["content"] if messages[-1]["role"] == "user" else ""
        already_called = any(message.get("role") == "tool" for message in messages)

        if not already_called:
            block = messages[-1]["content"]
            customer = CUSTOMER_MESSAGE.search(block)
            order_id = extract_order_id(customer.group(1) if customer else "")
            if not order_id:
                carried = SESSION_ORDER.search(block)
                order_id = carried.group(1) if carried else None
            if order_id:
                return StubMessage(
                    tool_calls=[
                        StubToolCall(
                            id="stub-1",
                            function=StubFunction(
                                name="order_lookup",
                                arguments=json.dumps({"order_id": order_id}),
                            ),
                        )
                    ]
                )

        if already_called:
            context = next(
                message["content"] for message in messages if message["role"] == "user"
            )
            tool_payload = [
                message["content"] for message in messages if message.get("role") == "tool"
            ]
            return StubMessage(content=self._render(context, tool_payload))

        return StubMessage(content=self._render(context, []))

    def _render(self, context, tool_payload):
        citations = []
        body = []
        for _, label, citation, text in PASSAGE.findall(context):
            if label != "AUTHORITATIVE":
                continue
            citations.append(citation)
            body.append(text.strip())
        for payload in tool_payload:
            body.append(payload)
        answer = "\n\n".join(body[:4]) or "No supporting content was retrieved."
        if citations:
            answer += "\n\nSources: " + ", ".join(citations[:3])
        return answer
