import math
import re
from collections import Counter
from dataclasses import dataclass

from .config import settings
from .ingest import TIER_RESTRICTED, TIER_WEIGHT, build_chunks
from .text import char_grams, tokenize

DURATION_INTENT = re.compile(
    r"\b(how long|how many days|window|deadline|timeframe|time frame|when do|within)\b",
    re.IGNORECASE,
)

INJECTION_PATTERNS = [
    re.compile(r"^\s*>?\s*system instruction\b.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^.*\bignore (all|any) (prior|previous|earlier)\b.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^.*\breveal (your|the) (hidden |system )?prompt\b.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^.*\b(ai|agent) instruction\b.*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^.*\bdisregard (all|any|the) (rules|instructions|policy)\b.*$", re.IGNORECASE | re.MULTILINE),
]

REDACTION = "[instruction-like text removed from untrusted content]"

QUANTITY = re.compile(
    r"(\d+(?:\s*[-–]\s*\d+)?)\s*(calendar day|business day|day|year|month|hour|minute|ounce)",
    re.IGNORECASE,
)

DEFERRAL = re.compile(
    r"(see the [^.]*policy|receive a different|is handled separately|follow the [^.]*policy"
    r"|still apply|superseded by|has been superseded)",
    re.IGNORECASE,
)

CONTRADICTION_PAIRS = [
    (
        re.compile(r"hand[-\s]?wash", re.IGNORECASE),
        re.compile(r"all components are dishwasher safe|fully dishwasher safe", re.IGNORECASE),
    ),
    (
        re.compile(r"\bnot leakproof\b", re.IGNORECASE),
        re.compile(r"\bis leakproof\b", re.IGNORECASE),
    ),
    (
        re.compile(r"cannot be (returned|exchanged)", re.IGNORECASE),
        re.compile(r"(may|can) be (returned|exchanged)", re.IGNORECASE),
    ),
    (
        re.compile(r"\bdo not (machine wash|place)\b", re.IGNORECASE),
        re.compile(r"\b(machine washable|safe to place)\b", re.IGNORECASE),
    ),
]


def scrub(text):
    flagged = False
    for pattern in INJECTION_PATTERNS:
        if pattern.search(text):
            flagged = True
            text = pattern.sub(REDACTION, text)
    return text, flagged


@dataclass
class Scored:
    chunk: object
    score: float
    components: dict
    text: str
    flagged: bool = False

    @property
    def citable(self):
        return self.chunk.document.citable

    def to_trace(self):
        return {
            "chunk_id": self.chunk.chunk_id,
            "source": self.chunk.citation,
            "tier": self.chunk.document.tier,
            "status": self.chunk.document.status,
            "authority": self.chunk.document.authority,
            "score": round(self.score, 4),
            "components": {key: round(value, 4) for key, value in self.components.items()},
            "contains_injection": self.flagged,
        }


class Retriever:
    def __init__(self, chunks=None, k1=1.5, b=0.75):
        self.chunks = chunks if chunks is not None else build_chunks()
        self.k1 = k1
        self.b = b
        self._word_docs = [tokenize(chunk.as_context()) for chunk in self.chunks]
        self._lengths = [len(doc) for doc in self._word_docs]
        self._avg_length = sum(self._lengths) / max(len(self._lengths), 1)
        self._word_counts = [Counter(doc) for doc in self._word_docs]
        self._word_idf = self._build_idf(self._word_counts)
        self._bm25_idf = self._build_bm25_idf(self._word_counts)
        self._word_vectors = [self._vector(counts, self._word_idf) for counts in self._word_counts]
        self._heading_tokens = [set(tokenize(chunk.heading)) for chunk in self.chunks]
        self._has_duration = [bool(QUANTITY.search(chunk.text)) for chunk in self.chunks]
        gram_counts = [Counter(char_grams(chunk.as_context())) for chunk in self.chunks]
        self._gram_idf = self._build_idf(gram_counts)
        self._gram_vectors = [self._vector(counts, self._gram_idf) for counts in gram_counts]

    def _build_idf(self, counts_list):
        total = len(counts_list)
        frequency = Counter()
        for counts in counts_list:
            frequency.update(counts.keys())
        return {term: math.log((total + 1) / (value + 0.5)) for term, value in frequency.items()}

    def _build_bm25_idf(self, counts_list):
        total = len(counts_list)
        frequency = Counter()
        for counts in counts_list:
            frequency.update(counts.keys())
        return {
            term: math.log(1 + (total - value + 0.5) / (value + 0.5))
            for term, value in frequency.items()
        }

    def _vector(self, counts, idf):
        vector = {}
        for term, count in counts.items():
            weight = (1 + math.log(count)) * idf.get(term, 0.0)
            if weight > 0:
                vector[term] = weight
        norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
        return {term: value / norm for term, value in vector.items()}

    def _cosine(self, query_vector, doc_vector):
        if len(query_vector) > len(doc_vector):
            query_vector, doc_vector = doc_vector, query_vector
        return sum(value * doc_vector.get(term, 0.0) for term, value in query_vector.items())

    def _bm25(self, query_tokens, index):
        counts = self._word_counts[index]
        length = self._lengths[index] or 1
        score = 0.0
        for term in query_tokens:
            frequency = counts.get(term)
            if not frequency:
                continue
            idf = self._bm25_idf.get(term, 0.0)
            denominator = frequency + self.k1 * (1 - self.b + self.b * length / self._avg_length)
            score += idf * frequency * (self.k1 + 1) / denominator
        return score

    def score(self, query):
        query_tokens = tokenize(query, expand=True)
        query_terms = set(query_tokens)
        duration_intent = bool(DURATION_INTENT.search(query))
        query_word_vector = self._vector(Counter(query_tokens), self._word_idf)
        query_gram_vector = self._vector(Counter(char_grams(query)), self._gram_idf)

        bm25 = [self._bm25(query_tokens, index) for index in range(len(self.chunks))]
        word = [self._cosine(query_word_vector, vector) for vector in self._word_vectors]
        gram = [self._cosine(query_gram_vector, vector) for vector in self._gram_vectors]

        bm25_max = max(bm25) or 1.0
        word_max = max(word) or 1.0
        gram_max = max(gram) or 1.0

        results = []
        for index, chunk in enumerate(self.chunks):
            components = {
                "bm25": bm25[index] / bm25_max,
                "tfidf": word[index] / word_max,
                "chargram": gram[index] / gram_max,
            }
            base = 0.5 * components["bm25"] + 0.3 * components["tfidf"] + 0.2 * components["chargram"]
            heading = self._heading_tokens[index]
            overlap = len(heading & query_terms) / len(heading) if heading else 0.0
            components["heading_boost"] = 1 + 0.3 * overlap
            components["intent_boost"] = 1.15 if duration_intent and self._has_duration[index] else 1.0
            components["authority_weight"] = TIER_WEIGHT[chunk.document.tier]
            base *= components["heading_boost"] * components["intent_boost"]
            text, flagged = scrub(chunk.text)
            results.append(
                Scored(
                    chunk=chunk,
                    score=base * components["authority_weight"],
                    components=components,
                    text=text,
                    flagged=flagged,
                )
            )
        results.sort(key=lambda item: item.score, reverse=True)
        return results

    def retrieve(self, query, top_k=None, per_document=2):
        top_k = top_k or settings.top_k
        ranked = self.score(query)
        if not ranked:
            return []
        best = ranked[0].score
        floor = max(0.16, 0.28 * best)
        selected = []
        seen = Counter()
        restricted_used = 0
        for item in ranked:
            if item.score < floor:
                break
            document = item.chunk.document
            allowance = per_document + 2 if document.filename == ranked[0].chunk.document.filename else per_document
            if seen[document.filename] >= allowance:
                continue
            if document.tier == TIER_RESTRICTED:
                if restricted_used >= 1 or item.score < 0.5 * best:
                    continue
                restricted_used += 1
            selected.append(item)
            seen[document.filename] += 1
            if len(selected) >= top_k:
                break
        return selected


def _quantities(text):
    values = {}
    for amount, unit in QUANTITY.findall(text):
        values.setdefault(unit.lower(), set()).add(amount.replace(" ", ""))
    return values


def _subject_overlap(first, second, idf):
    left = {token for token in tokenize(first.as_context()) if idf.get(token, 0) > 1.2}
    right = {token for token in tokenize(second.as_context()) if idf.get(token, 0) > 1.2}
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def find_conflicts(selected, idf):
    conflicts = []
    citable = [item for item in selected if item.citable]
    for index, first in enumerate(citable):
        for second in citable[index + 1:]:
            if first.chunk.document.filename == second.chunk.document.filename:
                continue
            if _subject_overlap(first.chunk, second.chunk, idf) < 0.10:
                continue
            if DEFERRAL.search(first.chunk.text) or DEFERRAL.search(second.chunk.text):
                continue
            reason = None
            left_quantities = _quantities(first.chunk.text)
            right_quantities = _quantities(second.chunk.text)
            for unit, values in left_quantities.items():
                other = right_quantities.get(unit)
                if other and not (values & other):
                    reason = "conflicting {0} values: {1} vs {2}".format(
                        unit, sorted(values), sorted(other)
                    )
                    break
            if reason is None:
                for left_pattern, right_pattern in CONTRADICTION_PAIRS:
                    matched = (
                        left_pattern.search(first.text) and right_pattern.search(second.text)
                    ) or (
                        right_pattern.search(first.text) and left_pattern.search(second.text)
                    )
                    if matched:
                        reason = "opposing guidance on the same subject"
                        break
            if reason:
                conflicts.append(
                    {
                        "sources": [first.chunk.citation, second.chunk.citation],
                        "reason": reason,
                    }
                )
    return conflicts
