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

## Other public benchmarks (not wired in)

| Benchmark | Size | Notes |
|---|---|---|
| [ReviewBench](https://github.blog/ai-and-ml/github-copilot/reviewbench-an-open-benchmark-for-ai-code-review/) | 219 PRs | self-serve runner takes a container image; license not stated in the post |
| [SWE-PRBench](https://arxiv.org/abs/2603.26130) | 350 PRs | [dataset](https://huggingface.co/datasets/foundry-ai/swe-prbench), [harness](https://github.com/FoundryHQ-AI/swe-prbench) (MIT); harness prompts raw models, so an adapter must feed it your reviewer's comments |
| [SWR-Bench](https://arxiv.org/abs/2509.01494) | 1,000 Python PRs | [repo](https://github.com/ZZR0/SWRench) (MIT); judge reads a predictions jsonl of `{instance_id, review}`; needs the repo at `base_commit` plus the PR diff |
| [c-CRAB](https://arxiv.org/abs/2603.23448) | 410 instances | [dataset](https://github.com/c-CRAB-Benchmark/dataset); passes only if a coding agent's fix passes tests derived from human comments, so it is the most expensive |

To add one: write `rbk/<name>.py` with `pr_urls()`/`export()`/`score()` that return the same normalized samples `compare.samples` reads.
