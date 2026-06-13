"""harness-guard.py 回帰テスト

設計レビュー(2026-06-13)指摘1への対応。セッション内で実施していた机上テスト
(companion regex 真陽性/偽陽性、フェイルクローズ、deny 優先、path 両形照合)を
versioned な資産として固定する。

検証方針: エンジンは sys.exit を多用しフックとして起動されるため、
import せず **サブプロセスとして実呼び出し**し、終了経路の不変条件
(exit 1 を一切踏まない / 判定は stdout JSON)まで含めて検証する。

実行: cd plugins/harness && python3 -m pytest tests/ -v
依存: pytest のみ(エンジン本体は標準ライブラリのみ)
"""
import json
import os
import subprocess
import sys

import pytest

# scripts/harness-guard.py を tests/ からの相対で解決
SCRIPT = os.path.join(os.path.dirname(__file__), os.pardir,
                      "scripts", "harness-guard.py")

# ---- 代表的なルールセット(init が生成するものの最小核) -----------------
RULES = {
    "version": 1,
    "rules": [
        {"id": "protect-harness-files-l1", "description": "L1",
         "action": "deny", "layer": "permission",
         "deny": ["Edit(.claude/harness-rules.json)"]},
        {"id": "protect-harness-files-l2", "description": "L2 保護",
         "action": "deny", "layer": "hook",
         "match": {"tool": "Edit|Write|MultiEdit|NotebookEdit",
                   "path_glob": "**/.claude/harness-rules.json"},
         "reason": "人間のみ"},
        {"id": "protect-harness-settings-l2", "description": "settings L2",
         "action": "deny", "layer": "hook",
         "match": {"tool": "Edit|Write|MultiEdit|NotebookEdit",
                   "path_glob": "**/.claude/settings*.json"},
         "reason": "人間のみ"},
        {"id": "protect-harness-files-bash", "description": "Bash 書込封鎖",
         "action": "deny", "layer": "hook",
         "match": {"tool": "Bash",
                   "command_regex": r"(>|\btee\b|\bsed\s+-[a-zA-Z]*i|"
                                    r"\b(cp|mv|rm|truncate|touch|dd|ln)\b)"
                                    r"[^|;&]*(\.claude/settings[^ /]*\.json|"
                                    r"harness-rules\.json)"},
         "reason": "迂回封鎖"},
        {"id": "no-force-push", "description": "force push 禁止",
         "action": "deny", "layer": "hook",
         "match": {"tool": "Bash",
                   "command_regex": r"git\s+push\b.*(--force\b|-f\b)"},
         "reason": "履歴破壊防止"},
        {"id": "confirm-db-migration", "description": "migration は承認後",
         "action": "ask", "layer": "hook",
         "match": {"tool": "Edit|Write", "path_glob": "**/db/migration/**"},
         "reason": "影響大"},
        {"id": "protect-tailwind", "description": "advisory",
         "action": "deny", "layer": "advisory", "note": "L3 候補"},
    ],
}


# ---- ヘルパ -------------------------------------------------------------

def run_guard(event, project_dir, env_project=True):
    """エンジンを実呼び出しし (exit_code, decision, reason) を返す。

    decision は stdout の判定 JSON から取得。判定が無い(素通り)場合は None。
    env_project=False のとき CLAUDE_PROJECT_DIR を渡さず cwd フォールバックを試す。
    """
    env = dict(os.environ)
    env.pop("HARNESS_GUARD_DEBUG", None)
    if env_project:
        env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    else:
        env.pop("CLAUDE_PROJECT_DIR", None)
    payload = event if isinstance(event, str) else json.dumps(event)
    proc = subprocess.run(
        [sys.executable, SCRIPT],
        input=payload, capture_output=True, text=True, env=env,
        cwd=str(project_dir),
    )
    decision = None
    reason = ""
    out = proc.stdout.strip()
    if out:
        doc = json.loads(out)["hookSpecificOutput"]
        decision = doc["permissionDecision"]
        reason = doc["permissionDecisionReason"]
    return proc.returncode, decision, reason


@pytest.fixture
def project(tmp_path):
    """harness-rules.json を備えたプロジェクトディレクトリ。"""
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "harness-rules.json").write_text(
        json.dumps(RULES, ensure_ascii=False), encoding="utf-8")
    return tmp_path


# ---- 不変条件: 終了経路は exit 0 のみ(exit 1 を絶対に踏まない) ----------
# 設計書 rev.2 実装規約1 / checklist §7。全テストが exit==0 を併せて主張する。

class TestExitCodeInvariant:
    def test_deny_exits_zero(self, project):
        code, dec, _ = run_guard(
            {"tool_name": "Bash",
             "tool_input": {"command": "git push origin main --force"}},
            project)
        assert dec == "deny"
        assert code == 0  # 判定は stdout、exit は 0(2 ですらない)

    def test_no_decision_exits_zero(self, project):
        code, dec, _ = run_guard(
            {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
            project)
        assert dec is None
        assert code == 0


# ---- L2 NEVER: deny ルール --------------------------------------------

class TestNeverDeny:
    def test_force_push_blocked(self, project):
        _, dec, reason = run_guard(
            {"tool_name": "Bash",
             "tool_input": {"command": "git push origin main --force"}},
            project)
        assert dec == "deny"
        assert "no-force-push" in reason  # 理由にルール id が乗る

    def test_force_push_word_order_independent(self, project):
        # rev.2.2 修正1: --force が末尾でもブロック(旧 regex の語順穴の回帰防止)
        _, dec, _ = run_guard(
            {"tool_name": "Bash",
             "tool_input": {"command": "git push --force origin main"}},
            project)
        assert dec == "deny"

    def test_normal_bash_passes(self, project):
        _, dec, _ = run_guard(
            {"tool_name": "Bash", "tool_input": {"command": "npm test"}},
            project)
        assert dec is None

    def test_l2_protects_rules_file_edit(self, project):
        _, dec, reason = run_guard(
            {"tool_name": "Edit",
             "tool_input": {"file_path": str(
                 project / ".claude" / "harness-rules.json")}},
            project)
        assert dec == "deny"
        assert "protect-harness-files-l2" in reason


# ---- L2 CONFIRM: ask ルールのモード対応 --------------------------------

class TestConfirmModeAware:
    MIG = {"tool_name": "Edit",
           "tool_input": {"file_path": "src/db/migration/V1__init.sql"}}

    def test_normal_mode_asks(self, project):
        _, dec, reason = run_guard(self.MIG, project)
        assert dec == "ask"
        assert "confirm-db-migration" in reason

    def test_bypass_mode_denies_and_stops(self, project):
        ev = dict(self.MIG, permission_mode="bypassPermissions")
        _, dec, reason = run_guard(ev, project)
        assert dec == "deny"  # bypass では ask が deny+停止に変換される
        assert "停止" in reason

    def test_bypass_key_camelcase(self, project):
        # detect_bypass はキー名の揺れに対応(permissionMode も読む)
        ev = dict(self.MIG, permissionMode="bypassPermissions")
        _, dec, _ = run_guard(ev, project)
        assert dec == "deny"


# ---- deny 優先(規約3): 同一操作が deny と ask 両方該当したら deny ------

class TestDenyWinsOverAsk:
    def test_deny_precedes_ask_regardless_of_order(self, tmp_path):
        # JSON 上は ask を先・deny を後に並べても deny が勝つ
        claude = tmp_path / ".claude"
        claude.mkdir()
        rules = {"version": 1, "rules": [
            {"id": "ask-rule", "description": "a", "action": "ask",
             "layer": "hook",
             "match": {"tool": "Edit", "path_glob": "**/x.txt"},
             "reason": "r1"},
            {"id": "deny-rule", "description": "d", "action": "deny",
             "layer": "hook",
             "match": {"tool": "Edit", "path_glob": "**/x.txt"},
             "reason": "r2"},
        ]}
        (claude / "harness-rules.json").write_text(
            json.dumps(rules), encoding="utf-8")
        _, dec, reason = run_guard(
            {"tool_name": "Edit", "tool_input": {"file_path": "dir/x.txt"}},
            tmp_path)
        assert dec == "deny"
        assert "deny-rule" in reason


# ---- path 両形照合(rev.2.1): 相対パス入力のすり抜け防止 ----------------

class TestPathCandidates:
    def test_relative_input_matches_glob(self, project):
        # 相対パス入力でも絶対パターン **/.claude/... にマッチさせる
        _, dec, _ = run_guard(
            {"tool_name": "Edit",
             "tool_input": {"file_path": ".claude/harness-rules.json"}},
            project)
        assert dec == "deny"

    def test_absolute_input_matches_glob(self, project):
        _, dec, _ = run_guard(
            {"tool_name": "Edit",
             "tool_input": {"file_path": str(
                 project / ".claude" / "harness-rules.json")}},
            project)
        assert dec == "deny"

    def test_unrelated_path_passes(self, project):
        _, dec, _ = run_guard(
            {"tool_name": "Edit",
             "tool_input": {"file_path": "src/main/App.tsx"}},
            project)
        assert dec is None


# ---- companion regex: 真陽性 -------------------------------------------

class TestCompanionTruePositives:
    @pytest.mark.parametrize("command", [
        "echo x >> .claude/settings.json",
        "echo x > .claude/settings.json",
        "sed -i s/a/b/ .claude/harness-rules.json",
        "cd .claude && echo x >> harness-rules.json",  # bare 名でも拾う
        "cp /tmp/evil .claude/settings.local.json",
        "mv /tmp/x .claude/harness-rules.json",
        "tee .claude/settings.json < /tmp/x",
        "rm .claude/harness-rules.json",
        "truncate -s0 .claude/settings.json",
    ])
    def test_bash_write_to_protected_is_denied(self, project, command):
        _, dec, reason = run_guard(
            {"tool_name": "Bash", "tool_input": {"command": command}},
            project)
        assert dec == "deny", f"想定: deny / 実際: {dec} ({command})"
        assert "protect-harness-files-bash" in reason


# ---- companion regex: 偽陽性(これらは素通りすべき) ---------------------

class TestCompanionTrueNegatives:
    @pytest.mark.parametrize("command", [
        "cat .claude/harness-rules.json",            # 読み出し
        "git checkout .claude/harness-rules.json",   # 人間の修復手順
        "grep deny .claude/settings.json",           # 読み出し
        "cat .claude/harness-rules.json > /tmp/x",   # 保護→他所への書き出し
    ])
    def test_read_and_repair_pass(self, project, command):
        _, dec, _ = run_guard(
            {"tool_name": "Bash", "tool_input": {"command": command}},
            project)
        assert dec is None, f"想定: 素通り / 実際: {dec} ({command})"


# ---- companion regex: 既知の偽陽性(レビュー指摘7) ----------------------
# 現状の振る舞いの記録。安全側に倒れた既知挙動であり「直すべきバグ」ではない。
# 将来 regex を改良してこの偽陽性を消したら、このテストが落ちて気づける。

class TestCompanionKnownFalsePositive:
    def test_grep_with_redirect_char_in_arg_is_denied(self, project):
        # grep の引数に > を含むと書込と誤判定される(指摘7)。
        # 現状の deny を固定。改善時はこのテストを更新すること。
        _, dec, _ = run_guard(
            {"tool_name": "Bash",
             "tool_input": {"command": "grep '>' .claude/harness-rules.json"}},
            project)
        assert dec == "deny"  # KNOWN: 安全側の偽陽性(指摘7)


# ---- 失敗時挙動 A/B/C(設計書 rev.2 失敗時挙動マトリクス) ---------------

class TestFailureModes:
    def test_a_missing_rules_file_opens(self, tmp_path):
        # シナリオ A: ルールファイル不在 → オープン(素通り、警告のみ)
        # force push という deny 対象でも、ルールが無ければ強制は無効
        _, dec, _ = run_guard(
            {"tool_name": "Bash",
             "tool_input": {"command": "git push --force"}},
            tmp_path)
        assert dec is None

    def test_b_broken_json_closes(self, tmp_path):
        # シナリオ B: JSON 破損 → クローズ(deny)
        claude = tmp_path / ".claude"
        claude.mkdir()
        (claude / "harness-rules.json").write_text(
            "{ broken json", encoding="utf-8")
        _, dec, reason = run_guard(
            {"tool_name": "Bash", "tool_input": {"command": "ls"}},
            tmp_path)
        assert dec == "deny"
        assert "破損" in reason

    def test_b_schema_violation_closes(self, tmp_path):
        # シナリオ B: スキーマ不適合(layer 誤記)→ クローズ(deny)
        # 規約: 誤記は黙殺=ルール失効ではなく deny に倒す
        claude = tmp_path / ".claude"
        claude.mkdir()
        bad = {"version": 1, "rules": [
            {"id": "x", "action": "deny", "layer": "typo",
             "match": {"tool": "Bash"}}]}
        (claude / "harness-rules.json").write_text(
            json.dumps(bad), encoding="utf-8")
        _, dec, _ = run_guard(
            {"tool_name": "Bash", "tool_input": {"command": "ls"}},
            tmp_path)
        assert dec == "deny"

    def test_stdin_broken_with_rules_closes(self, project):
        # stdin 破損 + ルール在り → クローズ(素通りの抜け穴を作らない)
        _, dec, reason = run_guard("THIS IS NOT JSON", project)
        assert dec == "deny"
        assert "解析" in reason

    def test_stdin_broken_without_rules_opens(self, tmp_path):
        # stdin 破損 + ルール不在 → オープン(未導入を邪魔しない)
        _, dec, _ = run_guard("NOT JSON", tmp_path)
        assert dec is None


# ---- cwd フォールバック(env 不在時) -----------------------------------

class TestCwdFallback:
    def test_resolves_via_cwd_when_env_absent(self, project):
        # CLAUDE_PROJECT_DIR が無くても event.cwd / cwd から解決する
        ev = {"tool_name": "Bash",
              "tool_input": {"command": "git push --force"},
              "cwd": str(project)}
        _, dec, _ = run_guard(ev, project, env_project=False)
        assert dec == "deny"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
