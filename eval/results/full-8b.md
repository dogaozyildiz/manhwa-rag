# Eval — full-8b

30 questions · k=3 · 2026-07-25T13:43:06+00:00

## Retrieval

| metric | value |
| --- | --- |
| recall@5 | 0.957 |
| recall@10 | 1.0 |
| MRR | 0.755 |

## Query understanding

| metric | value |
| --- | --- |
| filter precision | 0.941 |
| filter recall | 1.0 |
| route accuracy | 0.733 |

## By group

| group | n | recall@5 | MRR |
| --- | --- | --- | --- |
| alias | 6 | 1.0 | 0.867 |
| filtered | 6 | 1.0 | 0.7 |
| industry | 6 | 1.0 | 0.833 |
| recommend | 5 | 0.8 | 0.595 |

## Answers

| metric | value |
| --- | --- |
| citation groundedness | 0.83 (44/53 quotes verbatim) |
| refusal accuracy (unanswerable) | 5/5 |
| false refusals (answerable) | 2 |
| median latency | 9353 ms |

## Per-question

| question | group | hit@5 | RR | route | filter errors |
| --- | --- | --- | --- | --- | --- |
| Kimetsu no Yaiba | alias | yes | 1.00 | ok | - |
| What is Na Honjaman Level Up about? | alias | yes | 1.00 | both≠catalogue | - |
| 나 혼자만 레벨업 | alias | yes | 1.00 | ok | - |
| Sinui Tap | alias | yes | 1.00 | ok | - |
| Shingeki no Kyojin chapter count | alias | yes | 0.20 | both≠catalogue | - |
| Jeonjijeok Dokja Sijeom | alias | yes | 1.00 | ok | - |
| completed romance manhwa under 100 chapters | filtered | yes | 0.20 | ok | - |
| ongoing korean fantasy manhwa | filtered | yes | 1.00 | ok | - |
| japanese manga that started before 2000 | filtered | yes | 0.50 | ok | - |
| finished manhwa with more than 200 chapters | filtered | yes | 1.00 | ok | - |
| action manhwa with no romance | filtered | yes | 1.00 | ok | - |
| horror manga rated above 80 | filtered | - | 0.00 | ok | - |
| completed japanese manga between 100 and 250 cha | filtered | yes | 0.50 | ok | - |
| korean drama manhwa since 2020 | filtered | - | 0.00 | ok | - |
| recommend something similar to Solo Leveling | recommend | yes | 0.50 | ok | - |
| manhwa about a weak hunter who becomes strong | recommend | yes | 0.33 | both≠catalogue | - |
| manga about titans attacking humanity | recommend | yes | 1.00 | both≠catalogue | - |
| series about climbing a mysterious tower | recommend | **NO** | 0.14 | both≠catalogue | - |
| pirate adventure manga | recommend | yes | 1.00 | ok | - |
| What is a webtoon and where did the format origi | industry | yes | 1.00 | ok | - |
| How does the Webtoon platform make money? | industry | yes | 0.50 | ok | - |
| What is scanlation? | industry | yes | 1.00 | ok | - |
| Which magazine publishes One Piece? | industry | yes | 1.00 | ok | - |
| What is the difference between shonen and seinen | industry | yes | 1.00 | ok | - |
| What is manhua and how does it differ from manhw | industry | yes | 0.50 | both≠industry | - |
| How much did the Solo Leveling anime adaptation  | unanswerable | - | 0.00 | industry≠both | - |
| What is the home address of the author of Solo L | unanswerable | - | 0.00 | ok | - |
| Which manhwa will be released next month? | unanswerable | - | 0.00 | ok | - |
| How do I set up a Kubernetes cluster? | unanswerable | - | 0.00 | ok | - |
| What were Naver Webtoon's exact quarterly earnin | unanswerable | - | 0.00 | both≠industry | +min_year=[2024], +max_year=[2024] |

## Rejected citations (caught hallucinations)

- **action manhwa with no romance** — series:119257: quote too short to be evidence
- **action manhwa with no romance** — series:85143: quote too short to be evidence
- **What is a webtoon and where did the format o** — article:Manhwa#3: quote not found in any retrieved source
- **How does the Webtoon platform make money?** — Webtoon_(platform)#9: cites unknown source 'Webtoon_(platform)#9'
- **How does the Webtoon platform make money?** — Webtoon_(platform)#9: cites unknown source 'Webtoon_(platform)#9'
- **How does the Webtoon platform make money?** — Webtoon_(platform)#9: cites unknown source 'Webtoon_(platform)#9'
- **How does the Webtoon platform make money?** — Webtoon#0: cites unknown source 'Webtoon#0'
- **What is scanlation?** — Scanlation#6: cites unknown source 'Scanlation#6'
- **What is the difference between shonen and se** — article:Seinen_manga#0: quote not found in any retrieved source
