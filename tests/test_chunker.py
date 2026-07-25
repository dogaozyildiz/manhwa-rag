from app.ingest.chunker import chunk_document, count_tokens


def _filler(n: int) -> str:
    return " ".join(f"word{i}" for i in range(n))


def test_splits_on_headings_and_tracks_path():
    # Each section is given enough body that it cannot merge with its
    # neighbours, so the heading path of each is preserved independently.
    text = (
        f"# Billing\n\n{_filler(120)}\n\n"
        f"## Refunds\n\n{_filler(120)}\n\n"
        f"### Annual plans\n\n{_filler(120)}\n"
    )
    chunks = chunk_document(text, doc_title="Billing", max_tokens=200, overlap_tokens=20)
    sections = [c.section for c in chunks]
    assert "Refunds" in sections
    assert "Refunds > Annual plans" in sections
    # The document title is stripped from every path — it is stored on the
    # document row, so repeating it in each chunk label is noise.
    assert not any(s.startswith("Billing") for s in sections)


def test_small_adjacent_sections_merge_under_their_parent_label():
    """Merging is intentional: a two-line subsection is a poor retrieval unit.

    A merged chunk keeps the first heading path it saw, which is the nearest
    common ancestor of the merged content — here the article root, so the label
    is empty once the title is stripped.
    """
    text = (
        "# Billing\n\nShort intro about billing that survives the filter.\n\n"
        "## Refunds\n\nRefunds are issued within 14 days.\n\n"
        "### Annual plans\n\nAnnual plans are refunded pro rata.\n"
    )
    chunks = chunk_document(text, doc_title="Billing", max_tokens=200)
    assert len(chunks) == 1
    assert chunks[0].section == ""
    # No content is lost in the merge.
    assert "pro rata" in chunks[0].text
    assert "14 days" in chunks[0].text


def test_headings_inside_code_fences_are_not_headings():
    text = (
        "# Setup\n\nRun the installer as shown below to get started quickly.\n\n"
        "```bash\n# This is a shell comment, not a heading\n"
        "## Neither is this\ninstall --now\n```\n\n"
        "More prose follows the code block here.\n"
    )
    chunks = chunk_document(text, doc_title="Setup", max_tokens=500)
    sections = {c.section for c in chunks}
    assert sections == {""}, sections
    assert "install --now" in "\n".join(c.text for c in chunks)


def test_oversized_section_is_windowed_with_overlap():
    body = " ".join(f"word{i}" for i in range(1200))
    text = f"# Doc\n\n## Big\n\n{body}\n"
    chunks = chunk_document(text, doc_title="Doc", max_tokens=200, overlap_tokens=50)
    assert len(chunks) > 1
    assert all(c.token_count <= 220 for c in chunks)
    # Consecutive windows must share content, or answers get severed at the seam.
    first_tail = set(chunks[0].text.split()[-40:])
    second_head = set(chunks[1].text.split()[:40])
    assert first_tail & second_head


def test_chunk_indices_are_contiguous_from_zero():
    text = "# T\n\n" + "\n\n".join(f"## S{i}\n\nBody text number {i}." for i in range(6))
    chunks = chunk_document(text, doc_title="T", max_tokens=30)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_embed_text_carries_context_but_stored_text_does_not():
    text = "# Auth\n\n## Sessions\n\nSessions expire after one hour by default.\n"
    chunk = chunk_document(text, doc_title="Auth", max_tokens=500)[-1]
    embedded = chunk.embed_text("Auth")
    assert embedded.startswith("Auth")
    assert "Sessions" in embedded
    # Stored text stays clean: citations quote it verbatim, so a context prefix
    # here would leak into cited spans.
    assert not chunk.text.startswith("Auth —")


def test_content_hash_is_stable_and_section_sensitive():
    a = chunk_document("# D\n\n## A\n\nSame body text here.\n", doc_title="D")[0]
    b = chunk_document("# D\n\n## A\n\nSame body text here.\n", doc_title="D")[0]
    c = chunk_document("# D\n\n## B\n\nSame body text here.\n", doc_title="D")[0]
    assert a.content_hash == b.content_hash
    assert a.content_hash != c.content_hash


def test_count_tokens_handles_special_token_strings():
    # Raw docs contain sequences like <|endoftext|>; encoding must not raise.
    assert count_tokens("plain text") > 0
    assert count_tokens("<|endoftext|> appears in this sentence") > 0
