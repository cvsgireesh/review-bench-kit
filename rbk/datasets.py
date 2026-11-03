"""Benchmark datasets, all reduced to one shape so a single judge pipeline scores them.

Every loader returns {pr_url: {"pr_title", "source_repo", "golden_comments": [{"comment", "severity"}],
"golden_source_file"}}. `golden_comments` are the findings a good reviewer should raise; an empty list
means a clean PR, where every comment is a false positive. Sources are cloned at pinned commits.
"""

from __future__ import annotations

import json
import subprocess
import urllib.request
from pathlib import Path

MARTIAN = ("https://github.com/withmartian/code-review-benchmark.git", "e616e849755441da38f18bf3adba2c9583b03803")
SOURCES = {
    "reviewbench": ("https://github.com/review-bench/ReviewBench.git", "228f2a8d662c9c1c12d25757e23c52c9a6170d5a"),
    "swr": ("https://github.com/ZZR0/SWRench.git", "67ae1d4395ac05f800d62b0e13678eadeb9fa5c7"),
    "ccrab": ("https://github.com/c-CRAB-Benchmark/dataset.git", "856dfa3102b8996d168c4f195217b7603e1d1bc6"),
}
HF = "https://huggingface.co/datasets/foundry-ai/swe-prbench/resolve/b87f5797aef3ed2c3153bb1304ea4d801d36ba6e/dataset"
NAMES = ("martian", "reviewbench", "swr", "prbench", "ccrab")


def clone(url: str, pin: str, dest: Path) -> Path:
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", "--filter=blob:none", url, str(dest)], check=True)
    subprocess.run(["git", "-C", str(dest), "checkout", "--quiet", pin], check=True)
    return dest


def source_dir(root: Path, name: str) -> Path:
    return root / "third_party" / name


def deps(name: str, root: Path) -> None:
    if name in SOURCES:
        clone(*SOURCES[name], source_dir(root, name))


def _lines(path: Path):
    """JSONL records; splitlines() would also split on U+2028 inside strings."""
    with open(path, encoding="utf-8") as f:
        yield from (json.loads(x) for x in f if x.strip())


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def _sev(s: str | None) -> str:
    return {"high": "High", "critical": "High", "medium": "Medium", "low": "Low"}.get((s or "").lower(), "Medium")


def reviewbench(root: Path) -> dict:
    base = source_dir(root, "reviewbench")
    out = {}
    for pr in json.loads((base / "corpus" / "manifest.json").read_text()):
        key = f"{pr['repo'].rstrip('/').split('github.com/')[1].replace('/', '_')}_{pr['pr_number']}-{pr['head'][:8]}"
        gold = json.loads((base / "golden" / f"{key}.json").read_text())
        out[pr["pr_url"]] = {
            "pr_title": pr["title"], "source_repo": pr["repo"].split("github.com/")[1], "golden_source_file": f"{key}.json",
            "golden_comments": [{"comment": f"{f['file']}:{f['start_line']}: {f['message']}", "severity": _sev(f.get("severity")),
                                 "category": f.get("category")} for f in gold["findings"] if f.get("tp_fp") == "tp"]}
    return out


def swr(root: Path) -> dict:
    out = {}
    for r in _lines(source_dir(root, "swr") / "data" / "swr_datasets_d5c5.jsonl"):
        url = f"https://github.com/{r['repo']}/pull/{r['instance_id'].rsplit('-', 1)[1]}"
        gold = []
        for c in r["changes"]:
            snippet = c["change_introducing"]["code_snippet"]
            gold.append({"comment": f"{snippet.splitlines()[0]}: {c['change_discussion']['discussion_summary']}",
                         "severity": "Medium", "category": c["change_type"]})
        out[url] = {"pr_title": r["pr_title"], "source_repo": r["repo"], "golden_comments": gold,
                    "golden_source_file": "swr_datasets_d5c5.jsonl"}
    return out


def ccrab(root: Path) -> dict:
    out = {}
    path = source_dir(root, "ccrab") / "results_preprocessed" / "preprocess_dataset.jsonl"
    for r in _lines(path):
        gold = [{"comment": f"{c['path']}: {c['text']}", "severity": "Medium"} for c in r["reference_review_comments"]]
        out[f"https://github.com/{r['repo']}/pull/{r['pull_number']}"] = {
            "pr_title": r["title"], "source_repo": r["repo"], "golden_comments": gold, "golden_source_file": "preprocess_dataset.jsonl"}
    return out


def prbench(root: Path) -> dict:
    """Golden = the changes human reviewers required. PRs with none are clean PRs."""
    cache = root / "third_party" / "prbench"
    cache.mkdir(parents=True, exist_ok=True)
    prs = cache / "prs.jsonl"
    if not prs.exists():
        prs.write_bytes(_get(f"{HF}/prs.jsonl"))
    out = {}
    for r in _lines(prs):
        ann = cache / f"{r['task_id']}_human.json"
        if not ann.exists():
            ann.write_bytes(_get(f"{HF}/annotations/{r['task_id']}_human.json"))
        a = json.loads(ann.read_text())
        gold = [{"comment": f"{c['file']}: {c['body']}", "severity": "Medium"} for c in a["requested_changes"]]
        out[r["pr_url"]] = {"pr_title": r["title"], "source_repo": r["repo"], "golden_comments": gold,
                            "golden_source_file": f"{r['task_id']}_human.json"}
    return out


def load(name: str, root: Path) -> dict:
    if name == "martian":
        from . import martian
        return martian.dataset(root)
    try:
        fn = {"reviewbench": reviewbench, "swr": swr, "prbench": prbench, "ccrab": ccrab}[name]
    except KeyError:
        raise SystemExit(f"unknown dataset '{name}'; choose one of {', '.join(NAMES)}") from None
    if name in SOURCES and not source_dir(root, name).exists():
        raise SystemExit(f"run `rbk deps --dataset {name}` first")
    return fn(root)
