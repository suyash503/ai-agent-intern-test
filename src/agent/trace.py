import json
import time
from datetime import datetime, timezone

from .config import settings

REDACTED_KEYS = ("api_key", "authorization", "llm_api_key", "token")


def _clean(value):
    if isinstance(value, dict):
        return {
            key: ("[redacted]" if key.lower() in REDACTED_KEYS else _clean(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_clean(item) for item in value]
    return value


class Trace:
    def __init__(self, session_id, message, echo=False):
        self.session_id = session_id
        self.trace_id = "{0}-{1}".format(session_id, int(time.time() * 1000))
        self.echo = echo
        self.started = time.time()
        self.record = {
            "trace_id": self.trace_id,
            "session_id": session_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_message": message,
            "history": [],
            "retrieval": {},
            "tool_calls": [],
            "events": [],
            "response": None,
        }

    def set(self, key, value):
        self.record[key] = _clean(value)

    def event(self, name, **payload):
        self.record["events"].append({"event": name, **_clean(payload)})

    def tool_call(self, name, arguments, result):
        self.record["tool_calls"].append(
            {"name": name, "arguments": _clean(arguments), "result": _clean(result)}
        )

    def finish(self, response, sources, handoff, handoff_reason):
        self.record["response"] = response
        self.record["sources"] = sources
        self.record["handoff"] = handoff
        self.record["handoff_reason"] = handoff_reason
        self.record["duration_ms"] = round((time.time() - self.started) * 1000)
        self.write()
        return self.record

    def write(self):
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        path = settings.log_dir / "trace-{0}.jsonl".format(self.session_id)
        line = json.dumps(self.record, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        if self.echo:
            print(json.dumps(self.record, ensure_ascii=False, indent=2))
