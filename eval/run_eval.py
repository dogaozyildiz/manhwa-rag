"""Evaluation harness.

Three tiers, separated by what they cost:

* **Retrieval** — recall@k, MRR. Local embeddings only, so a full run is free
  and instant. This is what you sweep when tuning.
* **Extraction** — filter precision/recall and routing accuracy. Pure rules, no
  model at all. This is the metric specific to this project: it measures
  whether "under 100 chapters" actually became `chapters < 100`, which no
  standard RAG benchmark captures.
* **Answers** — citation groundedness, refusal accuracy, answer grade. Needs a
  provider key and is rate-limited on a free tier, so it is opt-in.

    python -m eval.run_eval                 # free tiers only
    python -m eval.run_eval --with-answers  # adds the generation tier
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.answer.pipeline import answer_question, retrieve
from app.db import session_scope
from app.retrieval.filters import extract_filters
from app.retrieval.router import route_query

EVAL_DIR = Path(__file__).resolve().parent
RESULTS_DIR = EVAL_DIR / "results"

FILTER_FIELDS = [
    "country", "status", "min_chapters", "max_chapters",
    "min_year", "max_year", "min_score", "genres", "exclude_genres",
]


@dataclass
class QuestionResult:
    question: str
    group: str
    answerable: bool
    expected_refs: list[str] = field(default_factory=list)
    retrieved_refs: list[str] = field(default_factory=list)
    hit_at_5: bool = False
    hit_at_10: bool = False
    reciprocal_rank: float = 0.0
    # extraction tier
    route_expected: str | None = None
    route_actual: str | None = None
    route_correct: bool | None = None
    filter_tp: int = 0
    filter_fp: int = 0
    filter_fn: int = 0
    filter_errors: list[str] = field(default_factory=list)
    # answer tier
    answer: str | None = None
    refused: bool | None = None
    refusal_correct: bool | None = None
    n_claims: int = 0
    n_verified: int = 0
    rejected: list[str] = field(default_factory=list)
    latency_ms: int | None = None


def load_golden() -> list[dict]:
    return yaml.safe_load((EVAL_DIR / "golden.yaml").read_text(encoding="utf-8"))


def _ref_matches(expected: str, actual: str) -> bool:
    """Article refs carry a chunk suffix (`article:Manhwa#3`); a hit on any
    chunk of the expected article counts. Series refs must match exactly."""
    return actual == expected or actual.startswith(f"{expected}#")


def score_retrieval(item: dict, refs: list[str], result: QuestionResult) -> None:
    expected = item.get("expected_refs") or []
    result.retrieved_refs = refs[:10]
    if not expected:
        return
    def hit(upto: int) -> bool:
        return any(
            _ref_matches(e, a) for e in expected for a in refs[:upto]
        )
    result.hit_at_5 = hit(5)
    result.hit_at_10 = hit(10)
    for rank, actual in enumerate(refs, start=1):
        if any(_ref_matches(e, actual) for e in expected):
            result.reciprocal_rank = 1.0 / rank
            break


def score_filters(item: dict, result: QuestionResult) -> None:
    """Compare extracted predicates against the expected ones, field by field.

    Scored as precision/recall over predicates rather than exact-match, because
    partial extraction is partially useful: getting `country` right and missing
    `max_chapters` is a better outcome than getting both wrong, and an
    all-or-nothing metric would hide that.
    """
    expected = item.get("expected_filters") or {}
    actual = extract_filters(item["question"])

    for field_name in FILTER_FIELDS:
        want = expected.get(field_name)
        got = getattr(actual, field_name)
        want_set = set(want) if isinstance(want, list) else ({want} if want else set())
        got_set = set(got) if isinstance(got, list) else ({got} if got else set())

        result.filter_tp += len(want_set & got_set)
        result.filter_fp += len(got_set - want_set)
        result.filter_fn += len(want_set - got_set)
        if got_set - want_set:
            result.filter_errors.append(f"+{field_name}={sorted(got_set - want_set)}")
        if want_set - got_set:
            result.filter_errors.append(f"-{field_name}={sorted(want_set - got_set)}")


async def run(*, with_answers: bool, k: int) -> tuple[list[QuestionResult], dict]:
    items = load_golden()
    results: list[QuestionResult] = []

    async with session_scope() as session:
        for i, item in enumerate(items, 1):
            result = QuestionResult(
                question=item["question"],
                group=item["group"],
                answerable=item["answerable"],
                expected_refs=item.get("expected_refs") or [],
            )

            # --- extraction tier (free, no model) ---
            filters = extract_filters(item["question"])
            result.route_expected = item.get("expected_route")
            result.route_actual = route_query(item["question"], filters)
            if result.route_expected:
                result.route_correct = result.route_actual == result.route_expected
            score_filters(item, result)

            # --- retrieval tier (free, local embeddings) ---
            sources, _, _ = await retrieve(session, item["question"], k=max(10, k))
            score_retrieval(item, [s.ref for s in sources], result)

            # --- answer tier (needs a provider key) ---
            if with_answers:
                answer = await answer_question(session, item["question"], k=k)
                result.answer = answer.text
                result.refused = answer.refused
                result.refusal_correct = answer.refused == (not item["answerable"])
                result.n_claims = len(answer.claims)
                result.n_verified = len(answer.verified_claims)
                result.rejected = [
                    f"{c.ref}: {c.reason}" for c in answer.rejected_claims
                ]
                result.latency_ms = answer.latency_ms

            results.append(result)
            flag = "" if result.hit_at_5 or not result.expected_refs else "  MISS"
            print(f"  [{i}/{len(items)}] {result.group:<13} {item['question'][:52]}{flag}")

    return results, summarise(results, k, with_answers)


def summarise(results: list[QuestionResult], k: int, with_answers: bool) -> dict:
    scored = [r for r in results if r.expected_refs]
    routed = [r for r in results if r.route_correct is not None]
    tp = sum(r.filter_tp for r in results)
    fp = sum(r.filter_fp for r in results)
    fn = sum(r.filter_fn for r in results)

    summary: dict = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "k": k,
        "n_questions": len(results),
        "recall_at_5": round(sum(r.hit_at_5 for r in scored) / len(scored), 3) if scored else None,
        "recall_at_10": round(sum(r.hit_at_10 for r in scored) / len(scored), 3) if scored else None,
        "mrr": round(statistics.mean(r.reciprocal_rank for r in scored), 3) if scored else None,
        "filter_precision": round(tp / (tp + fp), 3) if (tp + fp) else None,
        "filter_recall": round(tp / (tp + fn), 3) if (tp + fn) else None,
        "route_accuracy": round(sum(bool(r.route_correct) for r in routed) / len(routed), 3) if routed else None,
    }

    by_group: dict[str, dict] = {}
    for group in sorted({r.group for r in results}):
        rows = [r for r in results if r.group == group and r.expected_refs]
        if rows:
            by_group[group] = {
                "n": len(rows),
                "recall_at_5": round(sum(r.hit_at_5 for r in rows) / len(rows), 3),
                "mrr": round(statistics.mean(r.reciprocal_rank for r in rows), 3),
            }
    summary["by_group"] = by_group

    if with_answers:
        answered = [r for r in results if r.refused is not None]
        unanswerable = [r for r in answered if not r.answerable]
        answerable = [r for r in answered if r.answerable]
        claims = sum(r.n_claims for r in answered)
        verified = sum(r.n_verified for r in answered)
        summary |= {
            "groundedness": round(verified / claims, 3) if claims else None,
            "n_claims": claims,
            "n_rejected_claims": claims - verified,
            "refusal_accuracy": f"{sum(bool(r.refusal_correct) for r in unanswerable)}/{len(unanswerable)}",
            "false_refusals": sum(1 for r in answerable if r.refused),
            "median_latency_ms": int(statistics.median([r.latency_ms for r in answered if r.latency_ms])) if answered else None,
        }
    return summary


def write_report(results: list[QuestionResult], summary: dict, label: str) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"{label}.json").write_text(
        json.dumps({"summary": summary, "results": [asdict(r) for r in results]}, indent=2),
        encoding="utf-8",
    )

    lines = [
        f"# Eval — {label}",
        "",
        f"{summary['n_questions']} questions · k={summary['k']} · {summary['timestamp']}",
        "",
        "## Retrieval",
        "",
        "| metric | value |",
        "| --- | --- |",
        f"| recall@5 | {summary['recall_at_5']} |",
        f"| recall@10 | {summary['recall_at_10']} |",
        f"| MRR | {summary['mrr']} |",
        "",
        "## Query understanding",
        "",
        "| metric | value |",
        "| --- | --- |",
        f"| filter precision | {summary['filter_precision']} |",
        f"| filter recall | {summary['filter_recall']} |",
        f"| route accuracy | {summary['route_accuracy']} |",
        "",
        "## By group",
        "",
        "| group | n | recall@5 | MRR |",
        "| --- | --- | --- | --- |",
    ]
    for group, stats in summary["by_group"].items():
        lines.append(f"| {group} | {stats['n']} | {stats['recall_at_5']} | {stats['mrr']} |")
    lines.append("")

    if "groundedness" in summary:
        lines += [
            "## Answers",
            "",
            "| metric | value |",
            "| --- | --- |",
            f"| citation groundedness | {summary['groundedness']} "
            f"({summary['n_claims'] - summary['n_rejected_claims']}/{summary['n_claims']} quotes verbatim) |",
            f"| refusal accuracy (unanswerable) | {summary['refusal_accuracy']} |",
            f"| false refusals (answerable) | {summary['false_refusals']} |",
            f"| median latency | {summary['median_latency_ms']} ms |",
            "",
        ]

    lines += [
        "## Per-question",
        "",
        "| question | group | hit@5 | RR | route | filter errors |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        hit = "-" if not r.expected_refs else ("yes" if r.hit_at_5 else "**NO**")
        route = "ok" if r.route_correct else (f"{r.route_actual}≠{r.route_expected}" if r.route_expected else "-")
        errs = ", ".join(r.filter_errors) or "-"
        lines.append(
            f"| {r.question[:48]} | {r.group} | {hit} | {r.reciprocal_rank:.2f} | {route} | {errs} |"
        )
    lines.append("")

    rejected = [r for r in results if r.rejected]
    if rejected:
        lines += ["## Rejected citations (caught hallucinations)", ""]
        for r in rejected:
            for reason in r.rejected:
                lines.append(f"- **{r.question[:44]}** — {reason}")
        lines.append("")

    path = RESULTS_DIR / f"{label}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the evaluation suite.")
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("--with-answers", action="store_true",
                        help="also run the generation tier (needs GOOGLE_API_KEY)")
    parser.add_argument("--label", default=None)
    args = parser.parse_args()

    label = args.label or ("full" if args.with_answers else "retrieval")
    results, summary = asyncio.run(run(with_answers=args.with_answers, k=args.k))
    path = write_report(results, summary, label)
    print("\n" + json.dumps(summary, indent=2))
    print(f"\nreport: {path}")


if __name__ == "__main__":
    main()
