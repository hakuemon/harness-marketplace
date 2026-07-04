"""harness-verify.py Step 1 のテスト(仕様 §9)。

構成:
  Renderer   — 決定性 / 排他3分割 / 空節 / 描画形式の分岐
  CheckA     — 各コードの真陽性・真陰性(A-DUP は v0.2.2 実例の固定ケース)
  CheckB     — 緑 / ドリフト / マーカー全エッジ
  CLI        — 終了コード 0/2/3、exit-1-ゼロの二重検査、--json、未導入
"""

import copy
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parent.parent / "scripts" / "harness-verify.py"

# ハイフン入りファイル名のため importlib でロード(harness-guard のテストと同じ手法)
import importlib.util

_spec = importlib.util.spec_from_file_location("harness_verify", SCRIPT)
hv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hv)


# ---------------------------------------------------------------------------
# フィクスチャ
# ---------------------------------------------------------------------------

def make_rules(rules):
    return {"version": 1, "rules": rules}


R_L1 = {
    "id": "protect-harness-files-l1",
    "description": "ハーネス定義ファイルを改変から守る(L1)",
    "action": "deny",
    "layer": "permission",
    "deny": ["Edit(.claude/harness-rules.json)", "Write(.claude/harness-rules.json)"],
    "reason": "ルールファイルの改変は人間のみが行う",
}
R_HOOK_DENY = {
    "id": "no-merge-on-manual",
    "description": "MERGE_MODE=manual: PR のマージは人間が実行する(gh pr merge を禁止)",
    "action": "deny",
    "layer": "hook",
    "match": {"tool": "Bash", "command_regex": "gh\\s+pr\\s+merge\\b"},
    "reason": "PR のマージは人間が GitHub 上で実行してください",
}
R_ASK = {
    "id": "confirm-db-migration",
    "description": "DB マイグレーションファイルの編集は承認必須",
    "action": "ask",
    "layer": "hook",
    "match": {"tool": "Edit|Write", "path_glob": "db/migrations/**"},
    "reason": "スキーマ変更は不可逆になり得る",
}
R_ADVISORY = {
    "id": "no-secrets-in-code",
    "description": "秘密情報をコードに直書きしない",
    "action": "deny",
    "layer": "advisory",
    "note": "機械判定不能。L3 実装後の昇格候補",
}

GOOD_DOC = make_rules([R_L1, R_HOOK_DENY, R_ASK, R_ADVISORY])


def write_project(tmp_path: Path, doc=None, rules_md: str = None,
                  settings: dict = "auto", gitflow: str = "auto",
                  local: dict = "auto") -> Path:
    """一時プロジェクトを作る。既定では C/D/E も緑になる環境を合成する。

    settings / gitflow / local:
      "auto" = doc から緑状態を導出 / None = ファイルを作らない / 値 = その内容で作成
    """
    root = tmp_path
    (root / ".claude").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "claude").mkdir(parents=True, exist_ok=True)
    if doc is not None:
        (root / ".claude" / "harness-rules.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    if rules_md is None and doc is not None:
        rules_md = green_rules_md(doc)
    if rules_md is not None:
        (root / "docs" / "claude" / "rules.md").write_text(rules_md, encoding="utf-8")

    if doc is not None:
        rules = doc.get("rules", [])
        # C: settings.json = permission 層 deny の和集合
        if settings == "auto":
            deny = []
            for r in rules:
                if r.get("layer") == "permission":
                    for e in r.get("deny") or []:
                        if e not in deny:
                            deny.append(e)
            settings = {"permissions": {"deny": deny}}
        if settings is not None:
            (root / ".claude" / "settings.json").write_text(
                json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        # D: git-flow.md はルールの有無と整合するモードで生成
        if gitflow == "auto":
            ids = [r.get("id") for r in rules]
            if "no-merge-on-manual" in ids:
                gitflow = gitflow_md("manual")
            elif "no-direct-push-to-base" in ids:
                gitflow = gitflow_md("auto")
            else:
                gitflow = None  # git-flow 未採用 → N/A
        if gitflow is not None:
            (root / "docs" / "claude" / "git-flow.md").write_text(
                gitflow, encoding="utf-8")
        # E: settings.local.json + 実在する絶対パスの memory ディレクトリ
        if local == "auto":
            mem = root / "docs" / "claude" / "memory"
            mem.mkdir(parents=True, exist_ok=True)
            local = {"autoMemoryDirectory": str(mem)}
        if local is not None:
            (root / ".claude" / "settings.local.json").write_text(
                json.dumps(local, ensure_ascii=False, indent=2), encoding="utf-8")
    return root


def gitflow_md(mode: str) -> str:
    return ("# git-flow(テスト用)\n\n"
            "| 項目 | 値 |\n|---|---|\n"
            f"| **MERGE_MODE** | {mode} |\n"
            "| **BASE_BRANCH** | main |\n")


def green_rules_md(doc) -> str:
    """f(doc) をマーカー対に流し込んだ「緑」の rules.md を合成する。"""
    sections = hv.render_sections(doc)
    parts = ["# ルール(テスト用散文ヘッダ)", ""]
    for name in hv.SECTION_NAMES:
        parts.append(hv.begin_marker(name))
        parts.append(sections[name])
        parts.append(hv.end_marker(name))
        parts.append("")
    parts.append("固定散文フッタ(レンダラはここに触れない)")
    return "\n".join(parts) + "\n"


def run_cli(root: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "check", "--root", str(root), *extra],
        capture_output=True, text=True)


def codes(findings):
    return sorted(f.code for f in findings)


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

class TestRenderer:
    def test_deterministic_across_reparse(self):
        """決定性: 再パース → バイト一致。"""
        a = hv.render_sections(GOOD_DOC)
        b = hv.render_sections(json.loads(json.dumps(GOOD_DOC, ensure_ascii=False)))
        assert a == b

    def test_partition_is_total_and_exclusive(self):
        """4ルールが3節にちょうど1回ずつ現れる(全域性・排他性)。"""
        sections = hv.render_sections(GOOD_DOC)
        for rule in GOOD_DOC["rules"]:
            hits = [n for n in hv.SECTION_NAMES if f"**{rule['id']}**" in sections[n]]
            assert len(hits) == 1, rule["id"]

    def test_section_assignment(self):
        assert hv.section_of(R_L1) == "never-enforced"
        assert hv.section_of(R_HOOK_DENY) == "never-enforced"
        assert hv.section_of(R_ASK) == "confirm-machine"
        assert hv.section_of(R_ADVISORY) == "never-advisory"

    def test_advisory_wins_over_ask(self):
        """advisory ∧ ask は advisory 節のみ(初版試作で踏んだ重複所属バグの固定化)。"""
        rule = dict(R_ADVISORY, action="ask")
        assert hv.section_of(rule) == "never-advisory"

    def test_orphan_is_none(self):
        """ask ∧ permission は幽霊(permission 層に ask は存在しない)。"""
        assert hv.section_of(dict(R_L1, action="ask")) is None

    def test_empty_section_placeholder(self):
        sections = hv.render_sections(make_rules([R_L1]))
        assert sections["never-advisory"] == "(該当ルールなし)"
        assert sections["confirm-machine"] == "(該当ルールなし)"

    def test_array_order_preserved(self):
        doc = make_rules([R_HOOK_DENY, R_L1])  # 逆順
        body = hv.render_sections(doc)["never-enforced"]
        assert body.index("no-merge-on-manual") < body.index("protect-harness-files-l1")

    def test_permission_rendering(self):
        body = hv.render_rule(R_L1)
        assert "[L1 permission]" in body
        assert "- deny: `Edit(.claude/harness-rules.json)`" in body
        assert "理由: ルールファイルの改変は人間のみが行う" in body

    def test_hook_rendering_includes_raw_match(self):
        body = hv.render_rule(R_HOOK_DENY)
        assert "[L2 hook]" in body
        assert "tool=`Bash`" in body
        assert "regex=`gh\\s+pr\\s+merge\\b`" in body

    def test_note_rendering(self):
        assert "注記: 機械判定不能" in hv.render_rule(R_ADVISORY)

    def test_no_trailing_whitespace_or_crlf(self):
        for body in hv.render_sections(GOOD_DOC).values():
            assert "\r" not in body
            for line in body.split("\n"):
                assert line == line.rstrip()


# ---------------------------------------------------------------------------
# Check A
# ---------------------------------------------------------------------------

class TestCheckA:
    def test_green(self):
        assert hv.check_a(GOOD_DOC) == []

    def test_a_dup_v022_incident(self):
        """v0.2.2 実例(no-merge-on-manual 重複・PR #8 で解消)の固定ケース。"""
        dup = copy.deepcopy(R_HOOK_DENY)
        dup["description"] = "MERGE_MODE=manual 中の gh pr merge を禁止"
        doc = make_rules([R_L1, R_HOOK_DENY, dup])
        assert "A-DUP" in codes(hv.check_a(doc))

    def test_a_field_missing_core(self):
        doc = make_rules([{"description": "id も action も layer も無い"}])
        found = codes(hv.check_a(doc))
        assert "A-FIELD" in found

    def test_a_field_permission_without_deny(self):
        doc = make_rules([{k: v for k, v in R_L1.items() if k != "deny"}])
        assert "A-FIELD" in codes(hv.check_a(doc))

    def test_a_field_hook_without_match(self):
        doc = make_rules([{k: v for k, v in R_HOOK_DENY.items() if k != "match"}])
        assert "A-FIELD" in codes(hv.check_a(doc))

    def test_a_enum(self):
        doc = make_rules([dict(R_HOOK_DENY, layer="hooks"),
                          dict(R_L1, id="x", action="allow")])
        found = codes(hv.check_a(doc))
        assert found.count("A-ENUM") == 2

    def test_a_match_empty_is_dos(self):
        doc = make_rules([dict(R_HOOK_DENY, match={})])
        assert "A-MATCH" in codes(hv.check_a(doc))

    def test_a_match_missing_tool_and_pattern(self):
        doc = make_rules([dict(R_HOOK_DENY, match={"tool": "Bash"})])
        assert "A-MATCH" in codes(hv.check_a(doc))
        doc = make_rules([dict(R_HOOK_DENY, match={"command_regex": "x"})])
        assert "A-MATCH" in codes(hv.check_a(doc))

    def test_a_regex(self):
        doc = make_rules([dict(R_HOOK_DENY,
                               match={"tool": "Bash", "command_regex": "([unclosed"})])
        assert "A-REGEX" in codes(hv.check_a(doc))

    def test_a_orphan(self):
        doc = make_rules([dict(R_L1, action="ask")])
        assert "A-ORPHAN" in codes(hv.check_a(doc))

    def test_orphan_not_reported_for_bad_enum(self):
        """enum 不正のルールは A-ENUM のみ(A-ORPHAN の重複所見を出さない)。"""
        doc = make_rules([dict(R_HOOK_DENY, layer="hooks")])
        found = codes(hv.check_a(doc))
        assert "A-ENUM" in found and "A-ORPHAN" not in found


# ---------------------------------------------------------------------------
# Check B
# ---------------------------------------------------------------------------

class TestCheckB:
    def test_green(self, tmp_path):
        root = write_project(tmp_path, GOOD_DOC)
        assert hv.check_b(GOOD_DOC, root / "docs" / "claude" / "rules.md") == []

    def test_b_drift_stale_after_json_edit(self, tmp_path):
        """型1: JSON 編集後の render 忘れ → B-DRIFT+diff。"""
        root = write_project(tmp_path, GOOD_DOC)  # md は旧 JSON から生成
        new_doc = copy.deepcopy(GOOD_DOC)
        new_doc["rules"][1]["reason"] = "変更後の理由"
        findings = hv.check_b(new_doc, root / "docs" / "claude" / "rules.md")
        assert codes(findings) == ["B-DRIFT"]
        assert "変更後の理由" in findings[0].diff  # 期待値側に現れる

    def test_b_drift_hand_edit(self, tmp_path):
        """型2: マーカー内の手編集 → B-DRIFT。"""
        md = green_rules_md(GOOD_DOC).replace(
            "承認必須", "承認必須(手で書き足したメモ)")
        root = write_project(tmp_path, GOOD_DOC, rules_md=md)
        findings = hv.check_b(GOOD_DOC, root / "docs" / "claude" / "rules.md")
        assert codes(findings) == ["B-DRIFT"]

    def test_b_marker_missing_pair(self, tmp_path):
        md = green_rules_md(GOOD_DOC).replace(
            hv.begin_marker("never-advisory") + "\n", "").replace(
            hv.end_marker("never-advisory") + "\n", "")
        root = write_project(tmp_path, GOOD_DOC, rules_md=md)
        findings = hv.check_b(GOOD_DOC, root / "docs" / "claude" / "rules.md")
        assert [f.code for f in findings if f.target == "never-advisory"] == ["B-MARKER"]

    def test_b_marker_end_only(self, tmp_path):
        md = green_rules_md(GOOD_DOC).replace(hv.begin_marker("confirm-machine") + "\n", "")
        root = write_project(tmp_path, GOOD_DOC, rules_md=md)
        findings = hv.check_b(GOOD_DOC, root / "docs" / "claude" / "rules.md")
        assert any(f.code == "B-MARKER" and "BEGIN マーカーが欠落" in f.message
                   for f in findings)

    def test_b_marker_reversed(self, tmp_path):
        b, e = hv.begin_marker("never-enforced"), hv.end_marker("never-enforced")
        md = green_rules_md(GOOD_DOC)
        body = md[md.index(b):md.index(e) + len(e)]
        swapped = e + body[len(b):-len(e)] + b
        root = write_project(tmp_path, GOOD_DOC, rules_md=md.replace(body, swapped))
        findings = hv.check_b(GOOD_DOC, root / "docs" / "claude" / "rules.md")
        assert any(f.code == "B-MARKER" and "前にある" in f.message for f in findings)

    def test_b_marker_duplicated(self, tmp_path):
        b = hv.begin_marker("never-enforced")
        md = green_rules_md(GOOD_DOC).replace(b, b + "\n" + b, 1)
        root = write_project(tmp_path, GOOD_DOC, rules_md=md)
        findings = hv.check_b(GOOD_DOC, root / "docs" / "claude" / "rules.md")
        assert any(f.code == "B-MARKER" and "重複" in f.message for f in findings)

    def test_b_rules_md_absent(self, tmp_path):
        root = write_project(tmp_path, GOOD_DOC)
        (root / "docs" / "claude" / "rules.md").unlink()
        findings = hv.check_b(GOOD_DOC, root / "docs" / "claude" / "rules.md")
        assert codes(findings) == ["B-MARKER"]

    def test_prose_outside_markers_is_ignored(self, tmp_path):
        """散文(マーカー外)の編集は B の対象外 — レンダラの守備範囲の裏面。"""
        md = green_rules_md(GOOD_DOC).replace("固定散文フッタ", "書き換えた散文フッタ")
        root = write_project(tmp_path, GOOD_DOC, rules_md=md)
        assert hv.check_b(GOOD_DOC, root / "docs" / "claude" / "rules.md") == []


# ---------------------------------------------------------------------------
# CLI(subprocess: 終了コードと exit-1-ゼロ)
# ---------------------------------------------------------------------------

class TestCLI:
    def test_exit_0_green(self, tmp_path):
        root = write_project(tmp_path, GOOD_DOC)
        proc = run_cli(root)
        assert proc.returncode == 0
        assert "全チェック緑" in proc.stdout

    def test_exit_0_not_installed(self, tmp_path):
        proc = run_cli(tmp_path)  # 空ディレクトリ
        assert proc.returncode == 0
        assert "未導入" in proc.stdout

    def test_exit_2_findings(self, tmp_path):
        dup = copy.deepcopy(R_HOOK_DENY)
        root = write_project(tmp_path, make_rules([R_HOOK_DENY, dup]))
        proc = run_cli(root)
        assert proc.returncode == 2
        assert "[A-DUP]" in proc.stdout

    def test_exit_2_parse_error(self, tmp_path):
        root = write_project(tmp_path, GOOD_DOC)
        (root / ".claude" / "harness-rules.json").write_text("{壊れた", encoding="utf-8")
        proc = run_cli(root)
        assert proc.returncode == 2
        assert "[A-PARSE]" in proc.stdout

    def test_exit_3_internal_error(self, tmp_path):
        """harness-rules.json がディレクトリ = 予期しない環境異常 → exit 3。"""
        (tmp_path / ".claude" / "harness-rules.json").mkdir(parents=True)
        proc = run_cli(tmp_path)
        assert proc.returncode == 3

    def test_exit_3_usage_error(self, tmp_path):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "check", "--no-such-flag"],
            capture_output=True, text=True)
        assert proc.returncode == 3  # argparse 既定の 2 を奪還していること

    def test_exit_1_never_in_source(self):
        """不変条件①: ソースに exit(1) 経路が存在しない。"""
        src = SCRIPT.read_text(encoding="utf-8")
        assert not re.search(r"exit\(\s*1\s*\)", src)

    def test_exit_1_never_at_runtime(self, tmp_path):
        """不変条件②: 全シナリオ(緑・未導入・所見・破損・内部エラー)で 1 が出ない。"""
        scenarios = []
        scenarios.append(run_cli(write_project(tmp_path / "g", GOOD_DOC)))
        scenarios.append(run_cli(tmp_path / "empty_missing"))
        bad = write_project(tmp_path / "bad", make_rules([dict(R_L1, action="ask")]))
        scenarios.append(run_cli(bad))
        broken = write_project(tmp_path / "broken", GOOD_DOC)
        (broken / ".claude" / "harness-rules.json").write_text("{", encoding="utf-8")
        scenarios.append(run_cli(broken))
        (tmp_path / "e3" / ".claude" / "harness-rules.json").mkdir(parents=True)
        scenarios.append(run_cli(tmp_path / "e3"))
        assert all(p.returncode != 1 for p in scenarios)
        assert sorted({p.returncode for p in scenarios}) == [0, 2, 3]

    def test_json_output(self, tmp_path):
        dup = copy.deepcopy(R_HOOK_DENY)
        root = write_project(tmp_path, make_rules([R_HOOK_DENY, dup]))
        proc = run_cli(root, "--json")
        payload = json.loads(proc.stdout)
        assert payload["status"] == "findings"
        assert payload["findings"][0]["code"] == "A-DUP"

    def test_default_subcommand_is_check(self, tmp_path):
        root = write_project(tmp_path, GOOD_DOC)
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(root)],
            capture_output=True, text=True)
        assert proc.returncode == 0

    def test_check_is_read_only(self, tmp_path):
        """check は読取専用: 実行前後で全ファイルのバイト内容が不変。"""
        root = write_project(tmp_path, GOOD_DOC)
        before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
        run_cli(root)
        after = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
        assert before == after


# ---------------------------------------------------------------------------
# Check C(settings.json ↔ L1)
# ---------------------------------------------------------------------------

class TestCheckC:
    def test_green(self, tmp_path):
        root = write_project(tmp_path, GOOD_DOC)
        assert hv.check_c(GOOD_DOC, root / ".claude" / "settings.json") == []

    def test_c_missing_one_entry(self, tmp_path):
        settings = {"permissions": {"deny": [R_L1["deny"][0]]}}  # 2件中1件だけ
        root = write_project(tmp_path, GOOD_DOC, settings=settings)
        findings = hv.check_c(GOOD_DOC, root / ".claude" / "settings.json")
        assert codes(findings) == ["C-MISSING"]
        assert R_L1["deny"][1] in findings[0].message

    def test_c_extra_unmanaged_deny(self, tmp_path):
        settings = {"permissions": {"deny": R_L1["deny"] + ["Bash(rm -rf /)"]}}
        root = write_project(tmp_path, GOOD_DOC, settings=settings)
        findings = hv.check_c(GOOD_DOC, root / ".claude" / "settings.json")
        assert codes(findings) == ["C-EXTRA"]

    def test_c_settings_absent_with_l1_rules(self, tmp_path):
        root = write_project(tmp_path, GOOD_DOC, settings=None)
        findings = hv.check_c(GOOD_DOC, root / ".claude" / "settings.json")
        assert codes(findings) == ["C-MISSING"]

    def test_c_settings_absent_without_l1_rules(self, tmp_path):
        doc = make_rules([R_HOOK_DENY])
        root = write_project(tmp_path, doc, settings=None)
        assert hv.check_c(doc, root / ".claude" / "settings.json") == []

    def test_c_parse_error(self, tmp_path):
        root = write_project(tmp_path, GOOD_DOC)
        (root / ".claude" / "settings.json").write_text("{壊れた", encoding="utf-8")
        findings = hv.check_c(GOOD_DOC, root / ".claude" / "settings.json")
        assert codes(findings) == ["C-PARSE"]


# ---------------------------------------------------------------------------
# Check D(MERGE_MODE マトリクス全セル)
# ---------------------------------------------------------------------------

class TestCheckD:
    def _run(self, tmp_path, rules, gitflow):
        doc = make_rules(rules)
        root = write_project(tmp_path, doc, gitflow=gitflow)
        return hv.check_d(doc, root / "docs" / "claude" / "git-flow.md")

    def test_manual_1_pass(self, tmp_path):
        assert self._run(tmp_path, [R_HOOK_DENY], gitflow_md("manual")) == []

    def test_manual_0_dmode(self, tmp_path):
        f = self._run(tmp_path, [R_L1], gitflow_md("manual"))
        assert codes(f) == ["D-MODE"]

    def test_manual_2_ddup(self, tmp_path):
        f = self._run(tmp_path, [R_HOOK_DENY, copy.deepcopy(R_HOOK_DENY)],
                      gitflow_md("manual"))
        assert codes(f) == ["D-DUP"]

    def test_auto_0_pass(self, tmp_path):
        assert self._run(tmp_path, [R_L1], gitflow_md("auto")) == []

    def test_auto_1_dmode(self, tmp_path):
        f = self._run(tmp_path, [R_HOOK_DENY], gitflow_md("auto"))
        assert codes(f) == ["D-MODE"]

    def test_absent_no_git_rules_na(self, tmp_path):
        assert self._run(tmp_path, [R_L1, R_ASK], None) == []

    def test_absent_with_git_rules_dadopt(self, tmp_path):
        f = self._run(tmp_path, [R_HOOK_DENY], None)
        assert codes(f) == ["D-ADOPT"]

    def test_row_missing_dmode(self, tmp_path):
        f = self._run(tmp_path, [R_HOOK_DENY], "# git-flow\n(MERGE_MODE 行なし)\n")
        assert codes(f) == ["D-MODE"] and "見つからない" in f[0].message

    def test_invalid_value_dmode(self, tmp_path):
        f = self._run(tmp_path, [R_HOOK_DENY], gitflow_md("semi-auto"))
        assert codes(f) == ["D-MODE"] and "不正な値" in f[0].message


# ---------------------------------------------------------------------------
# Check E(運用ゲート機械化分)
# ---------------------------------------------------------------------------

class TestCheckE:
    def test_green(self, tmp_path):
        root = write_project(tmp_path, GOOD_DOC)
        assert hv.check_e(root) == []

    def test_e_local_absent(self, tmp_path):
        root = write_project(tmp_path, GOOD_DOC, local=None)
        assert codes(hv.check_e(root)) == ["E-LOCAL"]

    def test_e_mempath_relative(self, tmp_path):
        root = write_project(tmp_path, GOOD_DOC,
                             local={"autoMemoryDirectory": "docs/claude/memory"})
        f = hv.check_e(root)
        assert codes(f) == ["E-MEMPATH"] and "絶対パスでない" in f[0].message

    def test_e_mempath_nonexistent(self, tmp_path):
        root = write_project(tmp_path, GOOD_DOC,
                             local={"autoMemoryDirectory": str(tmp_path / "no-such")})
        f = hv.check_e(root)
        assert codes(f) == ["E-MEMPATH"] and "実在しない" in f[0].message

    def test_e_key_absent_is_ok(self, tmp_path):
        root = write_project(tmp_path, GOOD_DOC, local={})
        assert hv.check_e(root) == []

    def test_e_parse_error(self, tmp_path):
        root = write_project(tmp_path, GOOD_DOC)
        (root / ".claude" / "settings.local.json").write_text("{壊", encoding="utf-8")
        assert codes(hv.check_e(root)) == ["E-PARSE"]


# ---------------------------------------------------------------------------
# render サブコマンド
# ---------------------------------------------------------------------------

def run_render_cli(root: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "render", "--root", str(root), *extra],
        capture_output=True, text=True)


class TestRender:
    def test_no_change_when_green(self, tmp_path):
        root = write_project(tmp_path, GOOD_DOC)
        before = (root / "docs" / "claude" / "rules.md").read_bytes()
        proc = run_render_cli(root)
        assert proc.returncode == 0 and "変更なし" in proc.stdout
        assert (root / "docs" / "claude" / "rules.md").read_bytes() == before

    def test_render_repairs_drift_and_check_goes_green(self, tmp_path):
        root = write_project(tmp_path, GOOD_DOC)
        new_doc = copy.deepcopy(GOOD_DOC)
        new_doc["rules"][1]["reason"] = "変更後の理由"
        (root / ".claude" / "harness-rules.json").write_text(
            json.dumps(new_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        assert run_cli(root).returncode == 2          # B-DRIFT
        proc = run_render_cli(root)
        assert proc.returncode == 0 and "render 完了" in proc.stdout
        assert run_cli(root).returncode == 0          # 修復後は緑

    def test_prose_outside_markers_preserved_byte_exact(self, tmp_path):
        root = write_project(tmp_path, GOOD_DOC)
        md_path = root / "docs" / "claude" / "rules.md"
        new_doc = copy.deepcopy(GOOD_DOC)
        new_doc["rules"][0]["reason"] = "L1 の理由を変更"
        (root / ".claude" / "harness-rules.json").write_text(
            json.dumps(new_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        before = md_path.read_text(encoding="utf-8")
        run_render_cli(root)
        after = md_path.read_text(encoding="utf-8")
        # マーカー外(先頭ヘッダと末尾フッタ)がバイト不変
        assert after.startswith(before.split(hv.begin_marker("never-enforced"))[0])
        assert after.endswith(before.split(hv.end_marker("confirm-machine"))[-1])
        assert "L1 の理由を変更" in after

    def test_dry_run_writes_nothing(self, tmp_path):
        root = write_project(tmp_path, GOOD_DOC)
        new_doc = copy.deepcopy(GOOD_DOC)
        new_doc["rules"][1]["reason"] = "dry-run 用の変更"
        (root / ".claude" / "harness-rules.json").write_text(
            json.dumps(new_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        before = (root / "docs" / "claude" / "rules.md").read_bytes()
        proc = run_render_cli(root, "--dry-run")
        assert proc.returncode == 0 and "dry-run" in proc.stdout
        assert "dry-run 用の変更" in proc.stdout  # diff に期待値が現れる
        assert (root / "docs" / "claude" / "rules.md").read_bytes() == before

    def test_refuses_on_check_a_findings(self, tmp_path):
        dup = copy.deepcopy(R_HOOK_DENY)
        root = write_project(tmp_path, make_rules([R_HOOK_DENY, dup]))
        before = (root / "docs" / "claude" / "rules.md").read_bytes()
        proc = run_render_cli(root)
        assert proc.returncode == 2 and "[A-DUP]" in proc.stdout
        assert (root / "docs" / "claude" / "rules.md").read_bytes() == before

    def test_refuses_on_broken_markers(self, tmp_path):
        md = green_rules_md(GOOD_DOC).replace(
            hv.end_marker("never-advisory") + "\n", "")
        root = write_project(tmp_path, GOOD_DOC, rules_md=md)
        before = (root / "docs" / "claude" / "rules.md").read_bytes()
        proc = run_render_cli(root)
        assert proc.returncode == 2 and "[B-MARKER]" in proc.stdout
        assert (root / "docs" / "claude" / "rules.md").read_bytes() == before

    def test_render_idempotent(self, tmp_path):
        root = write_project(tmp_path, GOOD_DOC)
        new_doc = copy.deepcopy(GOOD_DOC)
        new_doc["rules"][2]["reason"] = "冪等性テスト"
        (root / ".claude" / "harness-rules.json").write_text(
            json.dumps(new_doc, ensure_ascii=False, indent=2), encoding="utf-8")
        run_render_cli(root)
        first = (root / "docs" / "claude" / "rules.md").read_bytes()
        proc = run_render_cli(root)
        assert "変更なし" in proc.stdout
        assert (root / "docs" / "claude" / "rules.md").read_bytes() == first


# ---------------------------------------------------------------------------
# template サブコマンド(lint)
# ---------------------------------------------------------------------------

TPL_RULES = [
    R_L1, R_HOOK_DENY,
    {"id": "{{NEVER_RULE_ID}}", "description": "{{NEVER_DESC}}",
     "action": "deny", "layer": "hook",
     "match": {"tool": "Bash", "command_regex": "{{COMMAND_REGEX}}"},
     "reason": "{{NEVER_REASON}}"},
    {"id": "{{CONFIRM_RULE_ID}}", "description": "{{CONFIRM_DESC}}",
     "action": "ask", "layer": "hook",
     "match": {"tool": "Edit|Write", "path_glob": "{{PATH_GLOB}}"},
     "reason": "{{CONFIRM_REASON}}"},
]


def run_template_cli(path: Path, *extra) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "template", str(path), *extra],
        capture_output=True, text=True)


class TestTemplate:
    def _write(self, tmp_path, rules):
        p = tmp_path / "harness-rules.json.template"
        p.write_text(json.dumps(make_rules(rules), ensure_ascii=False, indent=2),
                     encoding="utf-8")
        return p

    def test_green_with_placeholders(self, tmp_path):
        p = self._write(tmp_path, TPL_RULES)
        proc = run_template_cli(p, "--expect-rules", "4")
        assert proc.returncode == 0, proc.stdout
        assert "lint 緑" in proc.stdout

    def test_placeholder_regex_not_flagged(self, tmp_path):
        """{{COMMAND_REGEX}} は re.compile 検査をスキップ(A-REGEX を出さない)。"""
        p = self._write(tmp_path, TPL_RULES)
        proc = run_template_cli(p)
        assert "[A-REGEX]" not in proc.stdout and proc.returncode == 0

    def test_dup_detected_incl_placeholder_ids(self, tmp_path):
        p = self._write(tmp_path, TPL_RULES + [copy.deepcopy(TPL_RULES[3])])
        proc = run_template_cli(p)
        assert proc.returncode == 2 and "[A-DUP]" in proc.stdout

    def test_v022_incident_would_have_been_caught(self, tmp_path):
        """PR #6 時点の重複がこの lint で CI 赤になっていたことの再現。"""
        dup = copy.deepcopy(R_HOOK_DENY)
        dup["description"] = "MERGE_MODE=manual 中の gh pr merge を禁止"
        p = self._write(tmp_path, [R_L1, R_HOOK_DENY, dup, *TPL_RULES[2:]])
        proc = run_template_cli(p, "--expect-rules", "4")
        assert proc.returncode == 2
        assert "[A-DUP]" in proc.stdout and "[T-COUNT]" in proc.stdout

    def test_t_count(self, tmp_path):
        p = self._write(tmp_path, TPL_RULES)
        proc = run_template_cli(p, "--expect-rules", "10")
        assert proc.returncode == 2 and "[T-COUNT]" in proc.stdout

    def test_real_regex_still_checked(self, tmp_path):
        broken = copy.deepcopy(R_HOOK_DENY)
        broken["match"]["command_regex"] = "([unclosed"
        p = self._write(tmp_path, [broken])
        proc = run_template_cli(p)
        assert proc.returncode == 2 and "[A-REGEX]" in proc.stdout

    def test_file_absent(self, tmp_path):
        proc = run_template_cli(tmp_path / "no-such.template")
        assert proc.returncode == 2 and "[A-PARSE]" in proc.stdout


# ---------------------------------------------------------------------------
# CLI 統合(Step 2 追加分)
# ---------------------------------------------------------------------------

class TestCLIStep2:
    def test_check_covers_cde(self, tmp_path):
        """C/D/E の所見が check 本流に乗ることの確認(各1例)。"""
        root = write_project(tmp_path, GOOD_DOC, settings={"permissions": {"deny": []}},
                             gitflow=gitflow_md("auto"), local=None)
        proc = run_cli(root)
        assert proc.returncode == 2
        for code in ("[C-MISSING]", "[D-MODE]", "[E-LOCAL]"):
            assert code in proc.stdout

    def test_green_message_lists_all_checks(self, tmp_path):
        proc = run_cli(write_project(tmp_path, GOOD_DOC))
        assert proc.returncode == 0
        for label in ("A:", "B:", "C:", "D:", "E:"):
            assert label in proc.stdout

    def test_exit_1_never_step2_paths(self, tmp_path):
        """exit-1-ゼロ: render / template 系の全シナリオでも 1 が出ない。"""
        procs = []
        g = write_project(tmp_path / "g", GOOD_DOC)
        procs.append(run_render_cli(g))                      # 変更なし → 0
        dup = copy.deepcopy(R_HOOK_DENY)
        bad = write_project(tmp_path / "bad", make_rules([R_HOOK_DENY, dup]))
        procs.append(run_render_cli(bad))                    # A 所見で拒否 → 2
        tpl = tmp_path / "t.template"
        tpl.write_text(json.dumps(make_rules(TPL_RULES)), encoding="utf-8")
        procs.append(run_template_cli(tpl))                  # 緑 → 0
        procs.append(run_template_cli(tpl, "--expect-rules", "99"))  # T-COUNT → 2
        procs.append(run_template_cli(tmp_path / "none.json"))       # 不在 → 2
        assert all(p.returncode != 1 for p in procs)
        assert sorted({p.returncode for p in procs}) == [0, 2]



# ---------------------------------------------------------------------------
# テンプレート ↔ スクリプトのマーカー同一性(v0.3。仕様 §3+実装追補6)
# ---------------------------------------------------------------------------

class TestTemplateMarkerSync:
    """マーカー文字列の正準はテンプレート、スクリプトは同一文字列の再現。
    どちらかが単独で変わったら本テストが赤になる(単一情報源の機械検証)。"""

    TPL = Path(__file__).parent.parent / "skills" / "init" / "templates" / "rules.md.template"

    def test_template_ships_exact_marker_pairs(self):
        text = self.TPL.read_text(encoding="utf-8")
        for name in hv.SECTION_NAMES:
            assert hv.begin_marker(name) in text, f"BEGIN 不一致: {name}"
            assert hv.end_marker(name) in text, f"END 不一致: {name}"

    def test_template_marker_count_exactly_one_pair_each(self):
        text = self.TPL.read_text(encoding="utf-8")
        for name in hv.SECTION_NAMES:
            assert text.count(hv.begin_marker(name)) == 1
            assert text.count(hv.end_marker(name)) == 1

    def test_shipped_template_sections_extractable(self):
        """出荷状態のテンプレートからマーカー抽出が成立する(B-MARKER にならない)。"""
        lines = self.TPL.read_text(encoding="utf-8").split("\n")
        for name in hv.SECTION_NAMES:
            body, err = hv.extract_section(lines, name)
            assert err is None, f"{name}: {err}"
            assert body, f"{name}: 本文が空(未生成プレースホルダ行があるはず)"
