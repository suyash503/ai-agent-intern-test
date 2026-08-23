import re

from .config import settings
from .orders import extract_order_id

FOLLOWUP_CUE = re.compile(
    r"^\s*(and|also|what about|how about|what if|and what about|ok what about|then)\b"
    r"|^\s*(does|do|is|are|can|will|would|should|when|how|why|what)\b[^?]{0,60}\b"
    r"(it|that|this|they|them|those|these|there|one|mine)\b",
    re.IGNORECASE,
)

PRONOUN_ONLY = re.compile(r"\b(it|that|this|they|them|those|these|one|mine)\b", re.IGNORECASE)

ORDER_INTENT = re.compile(
    r"\b(order|package|parcel|shipment|shipping|deliver\w*|arrive\w*|track\w*|status|cancel\w*|"
    r"dispatch\w*|refund\w*)\b",
    re.IGNORECASE,
)

CONTENT_WORD = re.compile(r"[A-Za-z]{3,}")


class Session:
    def __init__(self, session_id, max_turns=None):
        self.session_id = session_id
        self.max_turns = max_turns or settings.max_history_turns
        self.turns = []
        self.last_topic = None
        self.last_order_id = None

    def history(self):
        return list(self.turns[-self.max_turns * 2:])

    def add_user(self, message):
        self.turns.append({"role": "user", "content": message})

    def add_assistant(self, message):
        self.turns.append({"role": "assistant", "content": message})

    def is_followup(self, message):
        if not self.last_topic:
            return False
        words = CONTENT_WORD.findall(message)
        if len(words) <= 3:
            return True
        if len(words) <= 12 and FOLLOWUP_CUE.search(message):
            return True
        if len(words) <= 8 and PRONOUN_ONLY.search(message):
            return True
        return False

    def contextualize(self, message):
        explicit = extract_order_id(message)
        if explicit:
            self.last_order_id = explicit
        if self.is_followup(message):
            query = "{0} {1}".format(self.last_topic, message).strip()
            rewritten = True
        else:
            query = message
            rewritten = False
        self.last_topic = message if not rewritten else self.last_topic
        return query, rewritten

    def facts(self, message):
        facts = {}
        if (
            self.last_order_id
            and not extract_order_id(message)
            and ORDER_INTENT.search(message)
        ):
            facts["order_id_mentioned_earlier_in_this_session"] = self.last_order_id
        return facts

    def note_order(self, order_id):
        if order_id:
            self.last_order_id = order_id


class SessionStore:
    def __init__(self):
        self._sessions = {}

    def get(self, session_id):
        if session_id not in self._sessions:
            self._sessions[session_id] = Session(session_id)
        return self._sessions[session_id]

    def reset(self, session_id):
        self._sessions.pop(session_id, None)
