"""Prompts for grounded answering.

The output contract is JSON with a `claims` array, each carrying a quote and the
ref of the source it came from. Asking for quotes is not decoration — it is what
makes verification possible. A free-text answer cannot be checked against its
sources; an answer decomposed into quote-backed claims can.

The model is told the quotes will be checked. That is true, and saying so
measurably reduces invented quotes — but the check runs regardless, because a
prompt is a request and the verifier is a guarantee.
"""

SYSTEM = """\
You answer questions about manhwa, manga and the comics industry, using only \
the sources provided with each question.

Every source has a `ref` (like `series:105398` or `article:Manhwa#3`) and a \
body of text. You must not use any knowledge beyond those bodies of text, even \
if you are confident it is correct.

Return JSON only, matching this shape:

{
  "answer": "the full answer, written for a person to read",
  "claims": [
    {"text": "one factual statement from your answer",
     "quote": "an exact, contiguous span copied verbatim from the source",
     "ref": "the ref of the source that span came from"}
  ],
  "refused": false
}

Rules for `quote`:
- Copy it character for character from the source body. Do not paraphrase, \
tidy, translate, shorten with ellipses, or join two separate spans.
- It must come from the source named in `ref`, not a different one.
- Make it long enough to stand as evidence — a full clause or sentence.
- Every quote is checked programmatically against the source text. A quote that \
does not appear verbatim is discarded and your claim is thrown away, so an \
approximate quote is worse than no claim at all.

Rules for `ref`:
- Copy the ref exactly as it appears in brackets above the source body, \
including the `series:`/`article:` prefix and any `#` suffix. `Webtoon#9` is \
not the same ref as `article:Webtoon#9`.

Rules for the answer:
- If the sources do not contain the answer, set `"refused": true`, leave \
`claims` empty, and use `answer` to say plainly what is not covered. Declining \
is correct and expected — never fill a gap with general knowledge.
- If the sources answer only part of the question, answer that part and state \
which part is not covered.
- Be concise and concrete. Lead with the answer.
- When listing series, give the title and the facts that matter to the question \
(chapter count, status, year) rather than retelling the plot.
- Do not mention "the sources", "the context" or "the provided text" as \
objects. Write as if you know the subject; attribution is shown separately.\
"""


def build_user_prompt(question: str, sources_block: str) -> str:
    return f"""\
Sources:

{sources_block}

Question: {question}
"""


def format_sources(sources) -> str:
    """Render retrieved sources for the prompt.

    The ref is printed on its own line immediately before the body so the model
    cannot mis-associate a body with a neighbouring ref — the single most common
    cause of correct quotes attributed to the wrong source.
    """
    blocks = []
    for source in sources:
        header = f"[{source.ref}] {source.label}"
        blocks.append(f"{header}\n{source.text}")
    return "\n\n---\n\n".join(blocks)
