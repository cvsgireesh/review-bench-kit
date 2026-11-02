from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from . import compare, config, live, martian, runner


def _arms(cfg: dict, arg: str | None) -> list[str]:
    names = arg.split(",") if arg else list(cfg["arms"])
    unknown = [n for n in names if n not in cfg["arms"]]
    if unknown:
        raise SystemExit(f"unknown arm(s): {', '.join(unknown)}")
    return names


def cmd_deps(a) -> None:
    martian.deps(Path(a.root))


def cmd_run(a) -> None:
    cfg, root = config.load(a.config), Path(a.root)
    urls = martian.pr_urls(root)[: a.limit]
    failed = runner.run(cfg, urls, _arms(cfg, a.arms), a.reps, root, a.jobs, a.timeout)
    print(f"done; {len(failed)} run(s) failed (they are excluded from scoring and re-tried on the next `run`)")


def cmd_score(a) -> None:
    cfg, root = config.load(a.config), Path(a.root)
    work = root / "martian"
    martian.export(root, _arms(cfg, a.arms), work)
    for p in martian.score(root, work, cfg["judge"]):
        print("evaluations:", p)


def cmd_compare(a) -> None:
    cfg, root = config.load(a.config), Path(a.root)
    arms = _arms(cfg, a.arms)
    rules = yaml.safe_load(Path(a.decision).read_text()) if a.decision else None
    evals = {m: root / "martian" / "results" / m.strip().replace("/", "_") / "evaluations.json" for m in cfg["judge"]["models"]}
    res = compare.report(root, evals, a.baseline or cfg.get("baseline") or arms[0], arms, rules)
    out = Path(a.out)
    out.with_suffix(".json").write_text(json.dumps(res, indent=1))
    out.with_suffix(".md").write_text(compare.to_markdown(res))
    print(compare.to_markdown(res))


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

    s = add("deps", cmd_deps, help="clone the pinned Martian scorer")
    s.add_argument("--root", default="work")

    s = add("run", cmd_run, help="run arms on the benchmark PRs")
    s.add_argument("--config", required=True)
    s.add_argument("--root", default="work")
    s.add_argument("--arms", help="comma list; default all")
    s.add_argument("--reps", type=int, default=1, help="repeats per PR (3 measures run-to-run noise)")
    s.add_argument("--limit", type=int, default=None, help="first N PRs only")
    s.add_argument("--jobs", type=int, default=1)
    s.add_argument("--timeout", type=int, default=1800, help="seconds per review")

    s = add("score", cmd_score, help="judge the stored reviews (Martian steps 2, 2.5, 3)")
    s.add_argument("--config", required=True)
    s.add_argument("--root", default="work")
    s.add_argument("--arms")

    s = add("compare", cmd_compare, help="compare arms against the baseline and apply the decision rules")
    s.add_argument("--config", required=True)
    s.add_argument("--root", default="work")
    s.add_argument("--arms")
    s.add_argument("--baseline")
    s.add_argument("--decision", help="decision rules yaml")
    s.add_argument("--out", default="report", help="writes <out>.json and <out>.md")

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
