"""Split articles into retrievable chunks.

Two decisions here drive retrieval quality more than anything downstream:

1. **Heading-aware first, token-aware second.** A help article is already
   organised by the questions it answers. Splitting on headings keeps a whole
   answer in one chunk; only sections that overrun the token budget get a
   sliding window. Splitting purely by token count severs answers mid-step.

2. **Chunks are embedded with their context, stored without it.** The embedded
   text is prefixed with "<article title> — <heading path>" so an isolated chunk
   is still interpretable to the embedding model. The stored text stays raw,
   because that is what gets sent to Claude and what citations must quote
   verbatim — a prefix in the stored text would show up inside cited spans.

Code fences are tracked so that a `#` comment inside a bash block is not
mistaken for a markdown heading.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

import tiktoken

# cl100k_base is close enough for budgeting; exact parity with the embedding
# model's tokeniser is not required, we only need a stable length signal.
_ENC = tiktoken.get_encoding("cl100k_base")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def count_tokens(text: str) -> int:
    return len(_ENC.encode(text, disallowed_special=()))


@dataclass
class ChunkDraft:
    text: str
    section: str
    token_count: int
    chunk_index: int = 0

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(
            f"{self.section}\n{self.text}".encode("utf-8")
        ).hexdigest()

    def embed_text(self, doc_title: str) -> str:
        """Text actually sent to the embedding model — chunk plus its context."""
        prefix = f"{doc_title} — {self.section}" if self.section else doc_title
        return f"{prefix}\n\n{self.text}"


@dataclass
class _Section:
    heading_path: str
    lines: list[str]


def _split_sections(text: str) -> list[_Section]:
    """Group lines under their heading path, e.g. 'Billing > Refunds'."""
    sections: list[_Section] = []
    stack: list[tuple[int, str]] = []
    current = _Section(heading_path="", lines=[])
    in_fence = False

    for line in text.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence

        match = None if in_fence else _HEADING_RE.match(line)
        if match:
            # Close the previous section before starting a new one.
            if any(ln.strip() for ln in current.lines):
                sections.append(current)
            level = len(match.group(1))
            title = match.group(2).strip()
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            path = " > ".join(t for _, t in stack)
            current = _Section(heading_path=path, lines=[])
        else:
            current.lines.append(line)

    if any(ln.strip() for ln in current.lines):
        sections.append(current)
    return sections


def _window_tokens(
    text: str, max_tokens: int, overlap_tokens: int
) -> list[str]:
    """Sliding-window split for a section that exceeds the budget."""
    ids = _ENC.encode(text, disallowed_special=())
    if len(ids) <= max_tokens:
        return [text]

    step = max(1, max_tokens - overlap_tokens)
    out: list[str] = []
    for start in range(0, len(ids), step):
        piece = _ENC.decode(ids[start : start + max_tokens]).strip()
        if piece:
            out.append(piece)
        if start + max_tokens >= len(ids):
            break
    return out


def chunk_document(
    text: str,
    *,
    doc_title: str,
    max_tokens: int = 500,
    overlap_tokens: int = 80,
    min_tokens: int = 40,
) -> list[ChunkDraft]:
    """Split one article into chunks. Adjacent small sections are merged so a
    two-line heading does not become its own near-useless chunk."""
    drafts: list[ChunkDraft] = []
    buffer_text = ""
    buffer_section = ""

    def flush() -> None:
        nonlocal buffer_text, buffer_section
        body = buffer_text.strip()
        if body:
            drafts.append(
                ChunkDraft(
                    text=body,
                    section=buffer_section,
                    token_count=count_tokens(body),
                )
            )
        buffer_text = ""
        buffer_section = ""

    for section in _split_sections(text):
        body = "\n".join(section.lines).strip()
        if not body:
            continue
        header = section.heading_path
        tokens = count_tokens(body)

        if tokens > max_tokens:
            flush()
            for piece in _window_tokens(body, max_tokens, overlap_tokens):
                drafts.append(
                    ChunkDraft(
                        text=piece,
                        section=header,
                        token_count=count_tokens(piece),
                    )
                )
            continue

        candidate = f"{buffer_text}\n\n{body}".strip() if buffer_text else body
        if count_tokens(candidate) > max_tokens:
            flush()
            buffer_text, buffer_section = body, header
        else:
            buffer_text = candidate
            buffer_section = buffer_section or header

    flush()

    # Fold a trailing runt into its predecessor rather than emitting it alone.
    if len(drafts) > 1 and drafts[-1].token_count < min_tokens:
        tail = drafts.pop()
        merged = f"{drafts[-1].text}\n\n{tail.text}"
        drafts[-1] = ChunkDraft(
            text=merged,
            section=drafts[-1].section,
            token_count=count_tokens(merged),
        )

    # The loader prepends "# <title>" to every article, so the heading stack
    # starts with the title and every section path would otherwise read
    # "Billing > Billing > Refunds". The title is stored on the document row, so
    # drop it from the path here rather than repeating it in every label.
    for i, d in enumerate(drafts):
        d.chunk_index = i
        if d.section == doc_title:
            d.section = ""
        elif d.section.startswith(f"{doc_title} > "):
            d.section = d.section[len(doc_title) + 3 :]
    return drafts
