from src.agent.ingest import (
    TIER_AUTHORITATIVE,
    TIER_RESTRICTED,
    build_chunks,
    classify,
    load_documents,
    parse_front_matter,
    split_sections,
)


def documents_by_name():
    return {document.filename: document for document in load_documents()}


def test_front_matter_is_parsed():
    meta, body = parse_front_matter("---\nstatus: active\ntitle: Test\n---\n# Heading\n")
    assert meta["status"] == "active"
    assert meta["title"] == "Test"
    assert body.startswith("# Heading")


def test_active_official_customer_document_is_authoritative():
    assert documents_by_name()["01-returns-policy-current.md"].tier == TIER_AUTHORITATIVE


def test_superseded_internal_and_draft_documents_are_restricted():
    documents = documents_by_name()
    for filename in (
        "02-returns-policy-legacy.md",
        "13-support-escalation.md",
        "14-internal-content-migration-notes.md",
    ):
        assert documents[filename].tier == TIER_RESTRICTED
        assert documents[filename].citable is False


def test_classification_uses_metadata_only():
    assert classify({"status": "active", "audience": "customer", "policy_authority": "official"}) == TIER_AUTHORITATIVE
    assert classify({"status": "active", "audience": "customer", "policy_authority": "none"}) != TIER_AUTHORITATIVE
    assert classify(
        {"status": "active", "audience": "customer", "policy_authority": "official", "customer_answering": "false"}
    ) == TIER_RESTRICTED


def test_sections_are_split_on_second_level_headings():
    sections = split_sections("# Title\n\n## One\nalpha\n\n## Two\nbeta\n")
    assert [heading for heading, _ in sections] == ["One", "Two"]


def test_chunks_carry_filename_and_heading():
    chunk = next(item for item in build_chunks() if item.chunk_id.startswith("07-warranty"))
    assert chunk.citation.startswith("07-warranty.md > ")
    assert chunk.document.title
