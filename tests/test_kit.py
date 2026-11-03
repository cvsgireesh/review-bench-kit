import json
import random
import stat

import pytest

from rbk import collect, compare, datasets, judge_proxy, live, martian, normalize, runner, stats, workspace


def test_normalize_ocr_maps_fields_and_usage():
    raw = {"comments": [{"path": "a.py", "content": "bad", "start_line": 3, "end_line": 4,
                         "severity": "high", "category": "bug", "suggestion_code": "x=1"}],
           "summary": {"input_tokens": 10, "output_tokens": 2}}
    out = normalize.ocr(raw)
    assert out["comments"][0]["line"] == 3 and out["comments"][0]["body"].startswith("[high/bug] bad")
    assert out["usage"] == {"input_tokens": 10, "output_tokens": 2}


def test_normalize_generic_rejects_comment_without_body():
    with pytest.raises(ValueError):
        normalize.generic({"comments": [{"path": "a.py"}]})


def _samples(tp, fp, fn, n=30, seed=1):
    r = random.Random(seed)
    return {f"pr{i}": {"tp": tp + r.random() * .2, "fp": fp, "fn": fn, "tp_high": 1, "fn_high": 0, "comments": tp + fp,
                       "seconds": 100, "cost_usd": 1.0} for i in range(n)}


RULES = {"require": [{"metric": "recall", "better": "higher", "margin": 0.03},
                     {"metric": "precision", "better": "higher", "margin": 0.03}],
         "any_superior": [{"metric": "cost_usd_per_pr", "better": "lower"}]}


def test_decide_switches_when_equal_quality_and_cheaper():
    base = _samples(2, 2, 2)
    cand = {k: {**v, "cost_usd": 0.5} for k, v in _samples(2, 2, 2).items()}
    assert stats.decide(RULES, base, cand, boots=300)["verdict"] == "SWITCH"


def test_decide_keeps_when_recall_drops():
    base = _samples(3, 1, 1)
    cand = {k: {**v, "tp": 1, "fn": 3, "cost_usd": 0.5} for k, v in base.items()}
    d = stats.decide(RULES, base, cand, boots=300)
    assert d["verdict"] == "KEEP" and not d["require"][0]["pass"]


def test_decide_keeps_when_nothing_improves():
    base = _samples(2, 2, 2)
    assert stats.decide(RULES, base, _samples(2, 2, 2), boots=300)["verdict"] == "KEEP"  # same cost: no reason to switch


def _eval_entry(tool, tp, fp, fn):
    tps = [{"golden_comment": "g", "severity": "High"}] * tp
    fns = [{"golden_comment": "g", "severity": "Low"}] * fn
    return {"skipped": False, "true_positives": tps, "false_positives": [{}] * fp, "false_negatives": fns,
            "tp": tp, "fp": fp, "fn": fn, "total_candidates": tp + fp, "tool": tool}


def test_samples_average_repeats_and_read_usage(tmp_path):
    url = "https://github.com/o/r/pull/5"
    for k, secs in ((1, 10), (2, 30)):
        f = tmp_path / "runs" / "A" / workspace.slug(url) / f"r{k}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"status": "ok", "seconds": secs, "usage": {"input_tokens": 100, "output_tokens": 0, "cost_usd": 1}}))
    ev = tmp_path / "e.json"
    ev.write_text(json.dumps({url: {"A": _eval_entry("A", 2, 1, 1), "A@r2": _eval_entry("A@r2", 0, 3, 3)}}))
    (f.parent / "r1.rawout.claude.json").write_text("{}")  # an arm's sidecar must not be read as a run
    assert compare.error_counts(tmp_path, ["A"]) == {"A": (0, 2)}
    s = compare.samples(tmp_path, ev, ["A"])["A"][url]
    assert (s["tp"], s["fp"], s["fn"]) == (1, 2, 2) and s["tp_high"] == 1 and s["seconds"] == 20


def test_martian_export_writes_one_tool_per_repeat(tmp_path, monkeypatch):
    url = "https://github.com/o/r/pull/5"
    monkeypatch.setattr(martian, "dataset", lambda root: {url: {"pr_title": "t", "source_repo": "r",
                                                               "golden_comments": [], "golden_source_file": "r.json"}})
    for k in (1, 2):
        f = tmp_path / "runs" / "A" / workspace.slug(url) / f"r{k}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"status": "ok", "comments": [{"path": "a", "line": 1, "body": "b"}]}))
    (tmp_path / "runs" / "A" / workspace.slug(url) / "r1.rawout.claude.json").write_text("{}")  # arm sidecar file
    bad = tmp_path / "runs" / "A" / workspace.slug(url) / "r3.json"
    bad.write_text(json.dumps({"status": "error", "comments": []}))
    (tmp_path / "third_party/code-review-benchmark/offline/golden_comments").mkdir(parents=True)
    out = martian.export(tmp_path, ["A"], tmp_path / "w")
    tools = [r["tool"] for r in json.loads(out.read_text())[url]["reviews"]]
    assert tools == ["A", "A@r2"]  # the errored repeat is not scored as an empty review


def test_runner_records_failures_and_does_not_score_them(tmp_path, monkeypatch):
    url = "https://github.com/o/r/pull/5"
    pr = {"repo": str(tmp_path), "base": "b", "head": "h", "pr_url": url}
    monkeypatch.setattr(workspace, "checkout", lambda u, root: pr)
    ok = tmp_path / "ok.sh"
    ok.write_text('#!/bin/sh\necho \'{"comments":[{"path":"a","line":1,"body":"x"}]}\' > "$1"\n')
    ok.chmod(ok.stat().st_mode | stat.S_IEXEC)
    cfg = {"arms": {"good": {"cmd": f"{ok} {{out}}"}, "broken": {"cmd": "exit 3"}}}
    failed = runner.run(cfg, [url], ["good", "broken"], 1, tmp_path, 1, 30)
    assert len(failed) == 1 and "broken" in str(failed[0])
    g = json.loads((tmp_path / "runs/good" / workspace.slug(url) / "r1.json").read_text())
    assert g["status"] == "ok" and len(g["comments"]) == 1
    assert len(list((tmp_path / "runs/good").rglob("r*.json"))) == 1  # raw arm output is not read as a result


def test_reply_verdicts():
    assert live.reply_verdict("Fixed in 3a4cf5b: the check now handles it") == "accepted"
    assert live.reply_verdict("**Real.** Fixed in abc1234") == "accepted"
    assert live.reply_verdict("Already handled at this head, no change.") == "rejected"
    assert live.reply_verdict("Waiting on a decision") == "other"


def _thread(author, path, line, body, replies=(), outdated=False, resolved=False):
    c = [{"author": {"login": author}, "path": path, "line": line, "originalLine": line, "body": body}]
    c += [{"author": {"login": a}, "path": path, "line": line, "originalLine": line, "body": b} for a, b in replies]
    return {"isOutdated": outdated, "isResolved": resolved, "comments": {"nodes": c}}


def test_score_pr_counts_threads_and_human_overlap():
    ths = [_thread("bot1", "a.py", 10, "bug", [("dev", "Fixed in abcdef1")], outdated=True),
           _thread("bot1", "b.py", 5, "nit"),
           _thread("alice", "a.py", 14, "why?"),     # within 10 lines of bot thread -> overlap
           _thread("alice", "c.py", 1, "other"),     # no bot thread on c.py -> miss
           _thread("renovate[bot]", "d.py", 1, "dep")]
    row, mine = live.score_pr(ths, {"bot1"}, 10)
    assert row == {"threads": 2, "accepted": 1, "rejected": 0, "no_reply": 1, "code_changed": 1,
                   "human_threads": 2, "human_hit": 1}
    assert live.rates([row])["human_overlap_recall"] == 0.5


def test_search_falls_back_to_app_form_but_never_hides_errors(monkeypatch):
    calls = []

    def fake(args, tries=4):
        q = next(a for a in args if a.startswith("q="))
        calls.append(q)
        if "reviewed-by:app/" not in q:
            raise RuntimeError("The listed users cannot be searched")
        return "7\n9\n"

    monkeypatch.setattr(live, "_gh", fake)
    assert live.search_prs("o/r", "some-bot", None, None) == [7, 9] and len(calls) == 2

    def limited(args, tries=4):
        raise RuntimeError("secondary rate limit")

    monkeypatch.setattr(live, "_gh", limited)
    with pytest.raises(RuntimeError):
        live.search_prs("o/r", "some-bot", None, None)


def test_live_compare_detects_a_real_difference():
    mk = lambda acc: {"prs": {str(i): {"threads": 4, "accepted": acc, "rejected": 0, "no_reply": 0, "code_changed": acc,
                                       "human_threads": 4, "human_hit": 2} for i in range(40)}}
    res = live.compare(mk(1), mk(3), boots=300)
    m = res["metrics"]["accepted_rate"]
    assert m["diff"] == pytest.approx(0.5) and m["ci"][0] > 0


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def test_swr_adapter_maps_pr_url_and_keeps_clean_prs(tmp_path):
    change = {"change_type": "F.2 Logic", "change_introducing": {"code_snippet": "a/b.py\n@@ -1 +1 @@"},
              "change_discussion": {"discussion_summary": "off by one"}}
    _write_jsonl(tmp_path / "third_party/swr/data/swr_datasets_d5c5.jsonl", [
        {"repo": "o/r", "instance_id": "o__r-12", "pr_title": "bug", "changes": [change]},
        {"repo": "o/r", "instance_id": "o__r-13", "pr_title": "clean", "changes": []}])
    d = datasets.load("swr", tmp_path)
    assert d["https://github.com/o/r/pull/12"]["golden_comments"][0]["comment"] == "a/b.py: off by one"
    assert d["https://github.com/o/r/pull/13"]["golden_comments"] == []


def test_ccrab_adapter_survives_unicode_line_separators(tmp_path):
    _write_jsonl(tmp_path / "third_party/ccrab/results_preprocessed/preprocess_dataset.jsonl", [
        {"repo": "o/r", "pull_number": 7, "title": "t", "reference_review_comments": [{"path": "x.py", "text": "a b"}]}])
    d = datasets.load("ccrab", tmp_path)
    assert d["https://github.com/o/r/pull/7"]["golden_comments"][0]["comment"] == "x.py: a b"


def test_reviewbench_adapter_keeps_only_true_positives_with_severity(tmp_path):
    base = tmp_path / "third_party/reviewbench"
    (base / "corpus").mkdir(parents=True)
    (base / "golden").mkdir()
    pr = {"repo": "https://github.com/o/r", "pr_number": 5, "pr_url": "https://github.com/o/r/pull/5", "head": "abcdef0123", "title": "t"}
    (base / "corpus/manifest.json").write_text(json.dumps([pr]))
    findings = [{"file": "a.py", "start_line": 3, "message": "real", "tp_fp": "tp", "severity": "high"},
                {"file": "b.py", "start_line": 1, "message": "not real", "tp_fp": "fp", "severity": "low"}]
    (base / "golden/o_r_5-abcdef01.json").write_text(json.dumps({"findings": findings}))
    gold = datasets.load("reviewbench", tmp_path)["https://github.com/o/r/pull/5"]["golden_comments"]
    assert [(g["comment"], g["severity"]) for g in gold] == [("a.py:3: real", "High")]


def test_unknown_dataset_and_missing_sources_are_errors(tmp_path):
    with pytest.raises(SystemExit):
        datasets.load("nope", tmp_path)
    with pytest.raises(SystemExit):
        datasets.load("swr", tmp_path)  # sources not cloned yet


def test_collect_fetch_filters_by_login_and_wait_refuses_empty(monkeypatch):
    def fake(path):
        who = {"login": "my-bot[bot]"}
        if path.endswith("/comments") and "pulls" in path:
            return [{"user": who, "path": "a.py", "line": None, "original_line": 4, "body": "bug"},
                    {"user": {"login": "human"}, "path": "a.py", "line": 1, "body": "hi"}]
        if path.endswith("/reviews"):
            return [{"user": who, "body": "summary"}, {"user": who, "body": ""}]
        return []

    monkeypatch.setattr(collect, "_gh", fake)
    got = collect.fetch("https://github.com/o/r/pull/1", {"my-bot"})
    assert got == [{"path": "a.py", "line": 4, "body": "bug"}, {"path": "", "line": 0, "body": "summary"}]
    monkeypatch.setattr(collect, "_gh", lambda p: [])
    with pytest.raises(TimeoutError):  # a bot that never ran is a failure, not an empty review
        collect.wait("https://github.com/o/r/pull/1", {"my-bot"}, timeout=0, quiet=0, poll=0)


def test_proxy_parses_tool_calls_and_ignores_plain_text():
    calls = judge_proxy._parse_tool_calls('```json\n{"tool_calls": [{"name": "read", "arguments": {"path": "a"}}]}\n```')
    assert calls[0]["function"] == {"name": "read", "arguments": '{"path": "a"}'}
    assert judge_proxy._parse_tool_calls("Looks fine to me.") is None
