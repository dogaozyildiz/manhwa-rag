# Eval — 20b-hardening-on

30 questions · k=5 · 2026-11-20T10:25:39+00:00

## Retrieval

| metric | value |
| --- | --- |
| recall@5 | 0.957 |
| recall@10 | 1.0 |
| MRR | 0.732 |

## Query understanding

| metric | value |
| --- | --- |
| filter precision | 0.941 |
| filter recall | 1.0 |
| route accuracy | 0.733 |

## By group

| group | n | recall@5 | MRR |
| --- | --- | --- | --- |
| alias | 6 | 1.0 | 0.778 |
| filtered | 6 | 1.0 | 0.7 |
| industry | 6 | 1.0 | 0.833 |
| recommend | 5 | 0.8 | 0.595 |

## Answers

| metric | value |
| --- | --- |
| citation groundedness | 0.864 (70/81 quotes verbatim) |
| refusal accuracy (unanswerable) | 5/5 |
| false refusals (answerable) | 1 |
| median latency | 2841 ms |
| provider errors (excluded) | 0 |

## Per-question

| question | group | hit@5 | RR | route | filter errors |
| --- | --- | --- | --- | --- | --- |
| Kimetsu no Yaiba | alias | yes | 1.00 | ok | - |
| What is Na Honjaman Level Up about? | alias | yes | 1.00 | both≠catalogue | - |
| 나 혼자만 레벨업 | alias | yes | 0.33 | ok | - |
| Sinui Tap | alias | yes | 1.00 | ok | - |
| Shingeki no Kyojin chapter count | alias | yes | 0.33 | both≠catalogue | - |
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

- **completed romance manhwa under 100 chapters** — series:86964: quote not found in any retrieved source
- **completed romance manhwa under 100 chapters** — series:115000: quote not found in any retrieved source
- **completed romance manhwa under 100 chapters** — series:120440: quote not found in any retrieved source
- **completed romance manhwa under 100 chapters** — series:104677: quote not found in any retrieved source
- **completed romance manhwa under 100 chapters** — series:145551: quote not found in any retrieved source
- **japanese manga that started before 2000** — series:30149: quote belongs to 'series:30013', not 'series:30149'
- **japanese manga that started before 2000** — series:30011: quote not found in any retrieved source
- **recommend something similar to Solo Leveling** — series:179445: quote not found in any retrieved source
- **manhwa about a weak hunter who becomes stron** — article:Solo_Leveling#1: quote not found in any retrieved source
- **series about climbing a mysterious tower** — article:Tower_of_God#1: quote not found in any retrieved source
- **What is manhua and how does it differ from m** — article:Comics#9: quote not found in any retrieved source
