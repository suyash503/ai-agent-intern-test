import re

WORD = re.compile(r"[a-z0-9$]+")

STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "for", "in", "on", "at", "is", "are", "was", "were",
    "be", "been", "it", "its", "this", "that", "these", "those", "i", "my", "me", "we", "our", "you",
    "your", "do", "does", "did", "can", "could", "should", "would", "will", "have", "has", "had",
    "with", "from", "by", "as", "if", "not", "but", "so", "than", "then", "there", "here", "what",
    "when", "where", "how", "why", "who", "whom", "any", "all", "about", "into", "over", "after",
    "before", "very", "just", "also", "get", "got",
}

SYNONYMS = {
    "refund": ["return"],
    "refunds": ["return"],
    "money": ["refund"],
    "eta": ["estimated", "delivery", "arrive"],
    "arrive": ["delivery", "estimated"],
    "arrival": ["delivery", "estimated"],
    "dishwasher": ["wash", "clean", "care"],
    "wash": ["clean", "care"],
    "guarantee": ["warranty"],
    "lifetime": ["warranty"],
    "abroad": ["international"],
    "overseas": ["international"],
    "canada": ["international", "canadian"],
    "canadian": ["international"],
    "germany": ["international", "destination"],
    "member": ["trailplus", "membership"],
    "members": ["trailplus", "membership"],
    "broken": ["damaged", "defective"],
    "cracked": ["damaged", "defective"],
    "zipper": ["damaged", "defective"],
    "cancel": ["cancellation"],
    "package": ["order", "shipment"],
    "parcel": ["order", "shipment"],
    "vegan": ["material", "fabric"],
    "backpack": ["bag"],
    "tumbler": ["drinkware"],
    "coupon": ["promotional", "discount"],
}

SUFFIXES = ("ings", "ing", "ies", "ied", "es", "ed", "s")


def stem(token: str) -> str:
    if len(token) <= 4:
        return token
    for suffix in SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            base = token[: -len(suffix)]
            if suffix == "ies":
                return base + "y"
            return base
    return token


def tokenize(text: str, expand: bool = False) -> list:
    raw = WORD.findall(text.lower())
    tokens = []
    for token in raw:
        if token in STOPWORDS:
            continue
        tokens.append(token)
        if expand:
            tokens.extend(SYNONYMS.get(token, []))
    return [stem(token) for token in tokens]


def char_grams(text: str, low: int = 3, high: int = 5) -> list:
    normalized = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", text.lower())).strip()
    grams = []
    for size in range(low, high + 1):
        for index in range(len(normalized) - size + 1):
            gram = normalized[index: index + size]
            if gram.strip():
                grams.append(gram)
    return grams


def normalize_answer(text: str) -> str:
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("\u2018", "'").replace("\u2019", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()
