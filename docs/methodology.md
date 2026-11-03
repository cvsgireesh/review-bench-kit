# Methodology and sources

What review-bot teams publish about changing model or effort, and how this kit follows it. All vendor numbers are self-reported.

| Practice | Source | In the kit |
|---|---|---|
| Hold the harness fixed, vary one thing; report recall, actionable precision, comments per PR, minor/nit share, tokens, cost, latency | [CodeRabbit, Sonnet 5.5](https://www.coderabbit.ai/blog/sonnet-5-5-model-review), [Opus 5.5](https://www.coderabbit.ai/blog/opus-5-5-model-review) | one arm = one change; all those metrics in `compare` |
| Higher effort is not reliably better: more recall on hard cases, lower precision, more tokens | same posts | decision rules guard precision and comment volume together with recall |
| Offline benchmark first, then A/B online; offline direction matched online | [GitHub, ReviewBench](https://github.blog/ai-and-ml/github-copilot/reviewbench-an-open-benchmark-for-ai-code-review/) | `run/score/compare` offline, `live`/`live-compare` online |
| Read traces, not only scores; check cost and quality together | [GitHub, tooling post](https://github.blog/ai-and-ml/github-copilot/better-tools-made-copilot-code-review-worse-heres-how-we-actually-improved-it/) | per-run usage and errors are stored in `runs/` |
| Online metric: was the flagged issue fixed afterwards | [Cursor](https://cursor.com/blog/building-bugbot), [Martian online](https://github.com/withmartian/code-review-benchmark/blob/main/methodology/full.md) | `live` code-changed and accepted rates |
| Several judge families; state limits (product not model, static data, gold capped at human recall) | Martian methodology | `judge.models` is a list; verdict needs every judge |
| Never trust a self-run benchmark | Greptile's 82% vs an independent rerun at 45% | pin the scorer commit; pre-write `decision.yaml` |

## Datasets

All wired in as `--dataset` (see the README table): Martian, [ReviewBench](https://github.com/review-bench/ReviewBench), [SWE-PRBench](https://arxiv.org/abs/2603.26130), [SWR-Bench](https://arxiv.org/abs/2509.01494) and [c-CRAB](https://arxiv.org/abs/2603.23448).
Each loader in `rbk/datasets.py` maps the dataset's ground truth to golden findings (`comment`, `severity`) per PR; the same pinned Martian judge steps then score every dataset. That makes scores comparable across datasets inside this kit, but they are not the datasets' own leaderboard numbers: ReviewBench uses its own judge and matcher, SWE-PRBench its rubric, c-CRAB executes tests. Use them to compare your arms, not to publish a leaderboard score.

To add a dataset, write a loader returning `{pr_url: {"pr_title", "source_repo", "golden_comments": [{"comment", "severity"}], "golden_source_file"}}` and register it in `datasets.load`.
