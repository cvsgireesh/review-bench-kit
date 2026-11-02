"""Bridge to the Martian offline benchmark (MIT): 50 PRs, 173 golden comments.

We reuse its dataset and its extract / dedup / judge steps unchanged. This module only
  1. clones the scorer at a pinned commit,
  2. writes our normalized reviews into the benchmark_data.json shape it reads,
  3. runs its steps against a judge model of your choice (any OpenAI-compatible endpoint).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from . import config, workspace

REPO = "https://github.com/withmartian/code-review-benchmark.git"
PINNED = "e616e849755441da38f18bf3adba2c9583b03803"


def scorer_dir(root: Path) -> Path:
    return root / "third_party" / "code-review-benchmark" / "offline"


def deps(root: Path) -> None:
    top = root / "third_party" / "code-review-benchmark"
    if not top.exists():
        top.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", REPO, str(top)], check=True)
    subprocess.run(["git", "-C", str(top), "fetch", "--quiet", "origin", PINNED], check=True)
    subprocess.run(["git", "-C", str(top), "checkout", "--quiet", PINNED], check=True)
    print(f"Martian scorer at {PINNED[:10]} in {top}")


def dataset(root: Path) -> dict:
    """PR url -> {pr_title, source_repo, golden_comments, golden_source_file}. Other tools' reviews are dropped."""
    f = scorer_dir(root) / "results" / "benchmark_data.json"
    if not f.exists():
        raise SystemExit("run `rbk deps` first")
    data = json.loads(f.read_text())
    keep = ("pr_title", "source_repo", "golden_comments", "golden_source_file")
    return {url: {k: v[k] for k in keep} for url, v in data.items()}


def pr_urls(root: Path) -> list[str]:
    return list(dataset(root))


def tool_name(arm: str, rep: int) -> str:
    return arm if rep == 1 else f"{arm}@r{rep}"


def export(root: Path, arms: list[str], work: Path) -> Path:
    """Write work/results/benchmark_data.json with one 'tool' per arm and repeat."""
    data = dataset(root)
    for url, entry in data.items():
        entry["reviews"] = []
        o, r, n = workspace.parse_pr_url(url)
        for arm in arms:
            for f in sorted((root / "runs" / arm / workspace.slug(url)).glob("r*.json")):
                res = json.loads(f.read_text())
                if res["status"] != "ok":
                    continue
                rep = int(f.stem[1:])
                entry["reviews"].append({
                    "tool": tool_name(arm, rep),
                    "repo_name": f"{o}__{r}__{arm}__PR{n}__rbk",
                    "pr_url": url,
                    "review_comments": [{"path": c["path"], "line": c.get("line", 0), "body": c["body"]}
                                        for c in res["comments"]],
                })
    out = work / "results" / "benchmark_data.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1))
    golden = work / "golden_comments"
    if not golden.exists():
        golden.symlink_to(scorer_dir(root) / "golden_comments")
    return out


def score(root: Path, work: Path, judge: dict) -> list[Path]:
    """Run steps 2, 2.5 and 3 once per judge model; return the evaluations.json paths."""
    key, base = config.expand(judge["api_key"]), config.expand(judge["base_url"])
    outs = []
    for model in judge["models"]:
        env = {**os.environ, "MARTIAN_API_KEY": key, "MARTIAN_BASE_URL": base, "MARTIAN_MODEL": model,
               "PYTHONPATH": str(scorer_dir(root))}
        mdir = work / "results" / model.strip().replace("/", "_")
        for step in (["step2_extract_comments"], ["step2_5_dedup_candidates"]):
            subprocess.run([sys.executable, "-m", f"code_review_benchmark.{step[0]}"], cwd=work, env=env, check=True)
        subprocess.run([sys.executable, "-m", "code_review_benchmark.step3_judge_comments",
                        "--dedup-groups", str(mdir / "dedup_groups.json")], cwd=work, env=env, check=True)
        outs.append(mdir / "evaluations.json")
    return outs
