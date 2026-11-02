"""Turn judge output plus run logs into per-arm, per-PR samples, compare arms, and apply the decision rules."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from . import stats, workspace

HIGH = {"high", "critical"}


def _arm_of(tool: str) -> str:
    return tool.split("@r")[0]


def samples(root: Path, evaluations: Path, arms: list[str]) -> dict[str, dict[str, stats.Sample]]:
    """arm -> pr_url -> Sample, averaged over repeats."""
    ev = json.loads(evaluations.read_text())
    acc: dict[str, dict[str, list[dict]]] = {a: defaultdict(list) for a in arms}
    for url, tools in ev.items():
        for tool, e in tools.items():
            arm = _arm_of(tool)
            if arm not in acc or e.get("skipped"):
                continue
            hi = lambda xs: sum(1 for x in xs if str(x.get("severity", "")).lower() in HIGH)
            acc[arm][url].append({"tp": e["tp"], "fp": e["fp"], "fn": e["fn"],
                                  "tp_high": hi(e.get("true_positives", [])), "fn_high": hi(e.get("false_negatives", [])),
                                  "comments": e.get("total_candidates", 0)})
    out: dict[str, dict[str, stats.Sample]] = {}
    for arm, per_pr in acc.items():
        out[arm] = {}
        for url, reps in per_pr.items():
            row = {k: sum(r[k] for r in reps) / len(reps) for k in reps[0]}
            runs = [json.loads(f.read_text()) for f in (root / "runs" / arm / workspace.slug(url)).glob("r*.json")]
            runs = [r for r in runs if r["status"] == "ok"]
            if runs:
                row["seconds"] = sum(r["seconds"] for r in runs) / len(runs)
                row["cost_usd"] = sum(r["usage"].get("cost_usd") or 0 for r in runs) / len(runs)
                row["tokens"] = sum(r["usage"].get("input_tokens", 0) + r["usage"].get("output_tokens", 0)
                                    for r in runs) / len(runs)
            out[arm][url] = row
    return out


def error_counts(root: Path, arms: list[str]) -> dict[str, tuple[int, int]]:
    res = {}
    for a in arms:
        files = list((root / "runs" / a).glob("*/r*.json"))
        res[a] = (sum(1 for f in files if json.loads(f.read_text())["status"] != "ok"), len(files))
    return res


def summary_row(rows: list[stats.Sample]) -> dict:
    names = ["precision", "recall", "f1", "f2", "recall_high", "comments_per_pr", "seconds_per_pr",
             "cost_usd_per_pr", "tokens_per_pr"]
    return {n: stats.metric(n, rows) for n in names} | {"prs": len(rows)}


def report(root: Path, evaluations: dict[str, Path], baseline: str, arms: list[str], rules: dict | None) -> dict:
    """evaluations: judge-name -> path. Verdicts are per judge; an arm only SWITCHes if every judge agrees."""
    result: dict = {"baseline": baseline, "judges": {}, "errors": error_counts(root, arms)}
    for judge, path in evaluations.items():
        s = samples(root, path, arms)
        j = {"summary": {a: summary_row(list(s[a].values())) for a in arms}, "decisions": {}}
        if rules:
            for a in arms:
                if a != baseline:
                    j["decisions"][a] = stats.decide(rules, s[baseline], s[a])
        result["judges"][judge] = j
    if rules:
        result["verdicts"] = {a: ("SWITCH" if all(j["decisions"][a]["verdict"] == "SWITCH"
                                                  for j in result["judges"].values()) else "KEEP")
                              for a in arms if a != baseline}
    return result


def to_markdown(res: dict) -> str:
    L = [f"# Review benchmark comparison (baseline: {res['baseline']})", ""]
    bad = {a: e for a, e in res["errors"].items() if e[0]}
    if bad:
        L += ["**Run errors (excluded from scoring, fix before trusting the numbers):** "
              + ", ".join(f"{a} {e[0]}/{e[1]}" for a, e in bad.items()), ""]
    for judge, j in res["judges"].items():
        L += [f"## Judge: {judge}", "", "| arm | PRs | precision | recall | F1 | F2 | recall(high) | comments/PR | sec/PR | $/PR |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for a, r in j["summary"].items():
            L.append(f"| {a} | {r['prs']} | {r['precision']:.3f} | {r['recall']:.3f} | {r['f1']:.3f} | {r['f2']:.3f} | "
                     f"{r['recall_high']:.3f} | {r['comments_per_pr']:.1f} | {r['seconds_per_pr']:.0f} | {r['cost_usd_per_pr']:.3f} |")
        for a, d in j["decisions"].items():
            L += ["", f"### {a} vs {res['baseline']}: **{d['verdict']}**", "",
                  "| rule | baseline | diff | 95% CI | pass |", "|---|---|---|---|---|"]
            for kind in ("require", "any_superior"):
                for r in d[kind]:
                    L.append(f"| {kind}: {r['metric']} ({r['rule']}) | {r['baseline']:.4f} | {r['diff']:+.4f} | "
                             f"[{r['ci'][0]:+.4f}, {r['ci'][1]:+.4f}] | {'yes' if r['pass'] else 'NO'} |")
        L.append("")
    if "verdicts" in res:
        L += ["## Final (all judges must agree)", ""] + [f"- {a}: **{v}**" for a, v in res["verdicts"].items()]
    return "\n".join(L) + "\n"
