"""Paired bootstrap over PRs and the switch/keep decision rules."""

from __future__ import annotations

import random

Sample = dict  # one PR's numbers for one arm: tp, fp, fn, fn_high, tp_high, comments, seconds, cost_usd, tokens


def _div(a: float, b: float) -> float:
    return a / b if b else 0.0


def metric(name: str, rows: list[Sample]) -> float:
    s = lambda k: sum(r.get(k, 0.0) or 0.0 for r in rows)
    n = len(rows) or 1
    if name == "precision":
        return _div(s("tp"), s("tp") + s("fp"))
    if name == "recall":
        return _div(s("tp"), s("tp") + s("fn"))
    if name == "recall_high":
        return _div(s("tp_high"), s("tp_high") + s("fn_high"))
    if name in ("f1", "f2"):
        p, r, b2 = metric("precision", rows), metric("recall", rows), 1 if name == "f1" else 4
        return _div((1 + b2) * p * r, b2 * p + r)
    if name == "comments_per_pr":
        return s("comments") / n
    if name in ("seconds_per_pr", "cost_usd_per_pr", "tokens_per_pr"):
        return s(name.removesuffix("_per_pr")) / n
    raise ValueError(f"unknown metric {name}")


def paired_diff(base: dict[str, Sample], cand: dict[str, Sample], name: str, boots: int = 2000, seed: int = 7):
    """Return (point diff, ci_low, ci_high) of cand - base on the PRs both have, resampling PRs."""
    ids = sorted(set(base) & set(cand))
    if not ids:
        raise ValueError("no PRs in common")
    point = metric(name, [cand[i] for i in ids]) - metric(name, [base[i] for i in ids])
    rng = random.Random(seed)
    diffs = []
    for _ in range(boots):
        pick = [rng.choice(ids) for _ in ids]
        diffs.append(metric(name, [cand[i] for i in pick]) - metric(name, [base[i] for i in pick]))
    diffs.sort()
    return point, diffs[int(0.025 * boots)], diffs[int(0.975 * boots) - 1]


def check(rule: dict, base_value: float, diff: tuple[float, float, float]) -> tuple[bool, str]:
    """A rule passes when the confidence bound on (cand - base) stays inside the allowed margin.

    better: higher | lower. margin: absolute allowed loss; margin_pct: allowed loss as a share of the baseline.
    mode: non_inferior (default) or superior (the CI must exclude zero in the good direction).
    """
    point, lo, hi = diff
    margin = rule.get("margin", 0.0) + rule.get("margin_pct", 0.0) * abs(base_value)
    higher = rule.get("better", "higher") == "higher"
    if rule.get("mode", "non_inferior") == "superior":
        ok = lo > 0 if higher else hi < 0
        return ok, f"{'lo' if higher else 'hi'}={(lo if higher else hi):+.4f} must be {'>' if higher else '<'} 0"
    ok = lo >= -margin if higher else hi <= margin
    return ok, (f"lo={lo:+.4f} >= -{margin:.4f}" if higher else f"hi={hi:+.4f} <= +{margin:.4f}")


def decide(rules: dict, base: dict[str, Sample], cand: dict[str, Sample], boots: int = 2000) -> dict:
    """rules: {require: [rule...], any_superior: [rule...]}. SWITCH only if all require pass and (if given) one superior."""
    out = {"require": [], "any_superior": []}
    for kind in ("require", "any_superior"):
        for rule in rules.get(kind, []):
            d = paired_diff(base, cand, rule["metric"], boots)
            base_val = metric(rule["metric"], [base[i] for i in sorted(set(base) & set(cand))])
            ok, why = check({**rule, **({"mode": "superior"} if kind == "any_superior" else {})}, base_val, d)
            out[kind].append({"metric": rule["metric"], "baseline": base_val, "diff": d[0], "ci": [d[1], d[2]],
                              "pass": ok, "rule": why})
    req_ok = all(r["pass"] for r in out["require"])
    sup_ok = (not out["any_superior"]) or any(r["pass"] for r in out["any_superior"])
    out["verdict"] = "SWITCH" if req_ok and sup_ok else "KEEP"
    return out
