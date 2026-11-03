from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from . import collect, compare, config, datasets, judge_proxy, live, martian, mirror, runner


def _arms(cfg: dict, arg: str | None) -> list[str]:
    names = arg.split(",") if arg else list(cfg["arms"])
    unknown = [n for n in names if n not in cfg["arms"]]
    if unknown:
        raise SystemExit(f"unknown arm(s): {', '.join(unknown)}")
    return names


def _work(root: Path, dataset: str) -> Path:
    return root / "martian" if dataset == "martian" else root / "score" / dataset


def cmd_deps(a) -> None:
    martian.deps(Path(a.root))
    datasets.deps(a.dataset, Path(a.root))


def cmd_run(a) -> None:
    cfg, root = config.load(a.config), Path(a.root)
    urls = list(datasets.load(a.dataset, root))[: a.limit]
    failed = runner.run(cfg, urls, _arms(cfg, a.arms), a.reps, root, a.jobs, a.timeout)
    print(f"done; {len(failed)} run(s) failed (they are excluded from scoring and re-tried on the next `run`)")


def cmd_score(a) -> None:
    cfg, root = config.load(a.config), Path(a.root)
    work = _work(root, a.dataset)
    martian.export(root, _arms(cfg, a.arms), work, datasets.load(a.dataset, root))
    for p in martian.score(root, work, cfg["judge"]):
        print("evaluations:", p)


def cmd_compare(a) -> None:
    cfg, root = config.load(a.config), Path(a.root)
    arms = _arms(cfg, a.arms)
    rules = yaml.safe_load(Path(a.decision).read_text()) if a.decision else None
    evals = {m: _work(root, a.dataset) / "results" / m.strip().replace("/", "_") / "evaluations.json" for m in cfg["judge"]["models"]}
    res = compare.report(root, evals, a.baseline or cfg.get("baseline") or arms[0], arms, rules)
    out = Path(a.out)
    out.with_suffix(".json").write_text(json.dumps(res, indent=1))
    out.with_suffix(".md").write_text(compare.to_markdown(res))
    print(compare.to_markdown(res))


def cmd_judge_proxy(a) -> None:
    judge_proxy.serve(a.port, a.jobs)


def cmd_collect(a) -> None:
    bots = {b.removesuffix("[bot]") for b in a.bot}
    comments = collect.wait(a.pr_url, bots, a.timeout, a.quiet) if a.timeout else collect.fetch(a.pr_url, bots)
    if not comments:
        raise SystemExit(f"no comments by {', '.join(sorted(bots))} on {a.pr_url}")
    Path(a.out).write_text(json.dumps({"comments": comments}))
    print(f"{len(comments)} comment(s) -> {a.out}")


def cmd_mirror(a) -> None:
    print(mirror.open_pr(a.pr_url, a.target, Path(a.root)))


def cmd_live(a) -> None:
    res = live.run(a.repo, a.bot, a.also_bot, a.since, a.until, a.window, a.audit, Path(a.out))
    print(json.dumps(res["summary"], indent=1))


def cmd_live_compare(a) -> None:
    res = live.compare(json.loads(Path(a.a).read_text()), json.loads(Path(a.b).read_text()))
    print(f"a: {res['a_prs']} PRs, b: {res['b_prs']} PRs")
    for n, m in res["metrics"].items():
        print(f"{n:22} a={m['a']:.3f} b={m['b']:.3f} diff={m['diff']:+.3f} 95% CI [{m['ci'][0]:+.3f}, {m['ci'][1]:+.3f}]")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="rbk", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, **kw):
        s = sub.add_parser(name, **kw)
        s.set_defaults(fn=fn)
        return s

    def dataset_arg(s):
        s.add_argument("--dataset", default="martian", choices=datasets.NAMES, help="benchmark to use (default martian)")

    s = add("deps", cmd_deps, help="clone the pinned scorer and the dataset sources")
    s.add_argument("--root", default="work")
    dataset_arg(s)

    s = add("run", cmd_run, help="run arms on the benchmark PRs")
    s.add_argument("--config", required=True)
    s.add_argument("--root", default="work")
    dataset_arg(s)
    s.add_argument("--arms", help="comma list; default all")
    s.add_argument("--reps", type=int, default=1, help="repeats per PR (3 measures run-to-run noise)")
    s.add_argument("--limit", type=int, default=None, help="first N PRs only")
    s.add_argument("--jobs", type=int, default=1)
    s.add_argument("--timeout", type=int, default=1800, help="seconds per review")

    s = add("score", cmd_score, help="judge the stored reviews (Martian steps 2, 2.5, 3)")
    s.add_argument("--config", required=True)
    s.add_argument("--root", default="work")
    dataset_arg(s)
    s.add_argument("--arms")

    s = add("compare", cmd_compare, help="compare arms against the baseline and apply the decision rules")
    s.add_argument("--config", required=True)
    s.add_argument("--root", default="work")
    dataset_arg(s)
    s.add_argument("--arms")
    s.add_argument("--baseline")
    s.add_argument("--decision", help="decision rules yaml")
    s.add_argument("--out", default="report", help="writes <out>.json and <out>.md")

    s = add("judge-proxy", cmd_judge_proxy, help="serve an OpenAI-compatible endpoint backed by the claude CLI")
    s.add_argument("--port", type=int, default=8799)
    s.add_argument("--jobs", type=int, default=4, help="parallel claude calls")

    s = add("collect", cmd_collect, help="write a hosted bot's comments on a PR as a review file")
    s.add_argument("--pr-url", required=True)
    s.add_argument("--bot", action="append", required=True, help="bot login (repeatable)")
    s.add_argument("--out", required=True)
    s.add_argument("--timeout", type=int, default=0, help="wait up to N seconds for the bot to post (0 = read once)")
    s.add_argument("--quiet", type=int, default=60, help="with --timeout: seconds without new comments before reading is final")

    s = add("mirror", cmd_mirror, help="replay a benchmark PR in a repo where your bot is installed")
    s.add_argument("--pr-url", required=True)
    s.add_argument("--target", required=True, help="owner/name of the scratch repo")
    s.add_argument("--root", default="work")

    s = add("live", cmd_live, help="score a bot's real review threads on a GitHub repo")
    s.add_argument("--repo", required=True, help="owner/name")
    s.add_argument("--bot", required=True, help="the bot's GitHub login")
    s.add_argument("--also-bot", action="append", default=[], help="other bot logins to exclude from human threads")
    s.add_argument("--since", help="PR created on or after YYYY-MM-DD")
    s.add_argument("--until", help="PR created on or before YYYY-MM-DD")
    s.add_argument("--window", type=int, default=10, help="lines for the human-overlap recall proxy")
    s.add_argument("--audit", type=int, default=0, help="include N random threads with their verdict for manual checking")
    s.add_argument("--out", default="live.json")

    s = add("live-compare", cmd_live_compare, help="compare two live runs (e.g. before vs after a switch)")
    s.add_argument("a", help="baseline / before")
    s.add_argument("b", help="candidate / after")

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
