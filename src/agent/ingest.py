import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import settings

FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
SCALAR = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")

TIER_AUTHORITATIVE = "authoritative"
TIER_SUPPORTING = "supporting"
TIER_RESTRICTED = "restricted"

TIER_WEIGHT = {
    TIER_AUTHORITATIVE: 1.0,
    TIER_SUPPORTING: 0.88,
    TIER_RESTRICTED: 0.45,
}


@dataclass(frozen=True)
class Document:
    path: Path
    filename: str
    title: str
    meta: dict
    tier: str

    @property
    def document_id(self) -> str:
        return str(self.meta.get("document_id", self.filename))

    @property
    def status(self) -> str:
        return str(self.meta.get("status", "unknown"))

    @property
    def authority(self) -> str:
        return str(self.meta.get("policy_authority", "none"))

    @property
    def audience(self) -> str:
        return str(self.meta.get("audience", "internal"))

    @property
    def citable(self) -> bool:
        return self.tier != TIER_RESTRICTED

    def why_restricted(self) -> str:
        reasons = []
        if self.status != "active":
            reasons.append(f"status is {self.status}")
        if self.audience != "customer":
            reasons.append(f"audience is {self.audience}")
        if self.authority != "official":
            reasons.append(f"policy authority is {self.authority}")
        if str(self.meta.get("customer_answering", "true")).lower() == "false":
            reasons.append("marked as not usable for customer answers")
        return "; ".join(reasons)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document: Document
    heading: str
    text: str
    tokens: list = field(repr=False, default_factory=list)

    @property
    def citation(self) -> str:
        return f"{self.document.filename} > {self.heading}"

    def as_context(self) -> str:
        return f"{self.document.title}\n{self.heading}\n\n{self.text}"


def parse_front_matter(raw: str) -> tuple:
    match = FRONT_MATTER.match(raw)
    if not match:
        return {}, raw
    meta = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        found = SCALAR.match(line)
        if not found:
            continue
        key, value = found.group(1), found.group(2).strip()
        value = value.strip("'\"")
        meta[key] = value
    return meta, raw[match.end():]


def classify(meta: dict) -> str:
    status = str(meta.get("status", "")).lower()
    audience = str(meta.get("audience", "")).lower()
    authority = str(meta.get("policy_authority", "")).lower()
    answering = str(meta.get("customer_answering", "true")).lower()
    if status != "active" or audience != "customer" or answering == "false":
        return TIER_RESTRICTED
    if authority == "official":
        return TIER_AUTHORITATIVE
    return TIER_SUPPORTING


def split_sections(body: str) -> list:
    lines = body.splitlines()
    sections = []
    heading = "Overview"
    buffer = []
    for line in lines:
        if line.startswith("## "):
            if any(part.strip() for part in buffer):
                sections.append((heading, "\n".join(buffer).strip()))
            heading = line[3:].strip()
            buffer = []
        elif line.startswith("# "):
            continue
        else:
            buffer.append(line)
    if any(part.strip() for part in buffer):
        sections.append((heading, "\n".join(buffer).strip()))
    return sections


def load_documents(kb_dir: Path = None) -> list:
    kb_dir = kb_dir or settings.kb_dir
    documents = []
    for path in sorted(kb_dir.glob("*.md")):
        raw = path.read_text(encoding="utf-8")
        meta, body = parse_front_matter(raw)
        documents.append(
            Document(
                path=path,
                filename=path.name,
                title=str(meta.get("title", path.stem)),
                meta=meta,
                tier=classify(meta),
            )
        )
    return documents


def build_chunks(documents: list = None) -> list:
    documents = documents if documents is not None else load_documents()
    chunks = []
    for document in documents:
        raw = document.path.read_text(encoding="utf-8")
        _, body = parse_front_matter(raw)
        for index, (heading, text) in enumerate(split_sections(body)):
            chunks.append(
                Chunk(
                    chunk_id=f"{document.filename}#{index}",
                    document=document,
                    heading=heading,
                    text=text,
                )
            )
    return chunks
