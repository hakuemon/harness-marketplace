#!/usr/bin/env python3
"""harness-guard — meta-harness v0.2 ルール強制エンジン

PreToolUse フックとして全許可モードで発火し、プロジェクト側
.claude/harness-rules.json の layer:"hook" ルールを照合する。

実装規約(設計書 rev.2 の不変条件):
1. 終了経路は2つだけ — exit 0(決定なし)/ stdout に判定 JSON(+exit 0)。
   exit 1 への自然落下は構造的に排除する(exit 1 は非ブロックエラーで
   素通りするため、ポリシー強制に使ってはならない)。
2. 失敗時挙動 —
   A: ルールファイル不在        = オープン(exit 0 + stderr 警告)
   B: 在るが破損/スキーマ不適合 = クローズ(deny)
   C: 所在確認後の内部エラー    = 準クローズ(deny)
   ※ 所在確認はいかなる解析よりも先に行う。stdin が読めない場合も、
     ルールファイルが在る限りクローズに倒す(素通りの抜け穴を作らない)。
3. 照合 — deny ルールを先に全件評価し、次に ask。両方に該当したら deny が勝つ。
4. CONFIRM(action:"ask")はモード対応 — 通常: ask / bypassPermissions:
   deny + 停止指示(自律実行では「人間の承認が要る操作」=停止して報告)。
5. path_glob は絶対パス・プロジェクト相対パスの両形に対して照合する
   (相対パス入力によるすり抜けを防ぐ)。

デバッグ: 環境変数 HARNESS_GUARD_DEBUG=1 で stdin のキー一覧と検出モードを
stderr に出力する(スモークテスト項目4の検証用)。
"""
import json
import os
import re
import sys
from fnmatch import fnmatch

EVENT_NAME = "PreToolUse"
RULES_REL_PATH = os.path.join(".claude", "harness-rules.json")
BYPASS_MODES = {"bypassPermissions"}

# 大域 except から参照する状態(規約2の open/closed 判定に使う)
_STATE = {"rules_present": False}


# ---------------------------------------------------------------- 出力経路

def _emit(decision: str, reason: str) -> None:
    """判定 JSON を stdout に出して正常終了する(唯一の判定出力経路)。
    stdout が書けない極端な状況では、公式のブロック用 exit code 2 に落とす
    (exit 1 への落下だけは絶対に避ける — 非ブロックエラーで素通りするため)。
    """
    try:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": EVENT_NAME,
                "permissionDecision": decision,
                "permissionDecisionReason": reason,
            }
        }, ensure_ascii=False))
        sys.stdout.flush()
    except BaseException:
        try:
            sys.stderr.write(f"[harness-guard] {decision}: {reason}\n")
        except BaseException:
            pass
        sys.exit(2 if decision == "deny" else 0)
    sys.exit(0)


def deny(reason: str) -> None:
    _emit("deny", reason)


def ask(reason: str) -> None:
    _emit("ask", reason)


def no_decision(warning: str = "") -> None:
    """決定なし(承認ではない)。通常の許可フローへ委ねる。"""
    if warning:
        sys.stderr.write(f"[harness-guard] {warning}\n")
    sys.exit(0)


# ---------------------------------------------------------------- 照合

def _tool_in_filter(tool_name: str, tool_filter: str) -> bool:
    """match.tool("Edit|Write" 形式)との完全一致判定。空なら全許容。"""
    if not tool_filter:
        return True
    return tool_name in [t.strip() for t in tool_filter.split("|")]


def _path_candidates(file_path: str, project_dir: str) -> list:
    """絶対・相対の両形を生成し、相対パス入力でのすり抜けを防ぐ。"""
    cands = set()
    norm = os.path.normpath(file_path)
    cands.add(norm)
    if os.path.isabs(norm):
        try:
            rel = os.path.relpath(norm, project_dir)
            if not rel.startswith(".."):
                cands.add(rel)
                cands.add("/" + rel)  # `**/x/**` 形式のパターン用
        except ValueError:
            pass
    else:
        cands.add(os.path.normpath(os.path.join(project_dir, norm)))
        cands.add("/" + norm)
    return list(cands)


def rule_matches(rule: dict, tool_name: str, tool_input: dict,
                 project_dir: str) -> bool:
    match = rule.get("match")
    if not isinstance(match, dict):
        raise ValueError(f"rule '{rule.get('id')}': match がない/不正")
    if not _tool_in_filter(tool_name, str(match.get("tool", ""))):
        return False

    if "command_regex" in match:
        command = str(tool_input.get("command") or "")
        if not command:
            return False
        try:
            return re.search(match["command_regex"], command) is not None
        except re.error as exc:
            raise ValueError(
                f"rule '{rule.get('id')}': command_regex が不正 ({exc})")

    if "path_glob" in match:
        file_path = str(tool_input.get("file_path")
                        or tool_input.get("notebook_path") or "")
        if not file_path:
            return False
        pattern = str(match["path_glob"])
        return any(fnmatch(c, pattern)
                   for c in _path_candidates(file_path, project_dir))

    # tool 指定のみのルール(そのツール自体を対象とする)
    return True


def detect_bypass(event: dict) -> bool:
    """許可モードを読む。キー名の揺れに備えて複数候補を見る。
    注意: モードキーが取得できない場合は通常モード扱い(ask)に倒すが、
    bypass 環境で ask がどう扱われるかは実測対象(スモークテスト4・8)。
    キーが恒常的に欠落する場合はモード検出の代替設計に差し戻すこと。
    """
    for key in ("permission_mode", "permissionMode", "permission_mode_name"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value in BYPASS_MODES
    return False


def load_rules(rules_path: str) -> list:
    """ルールファイルを読み、軽量スキーマ検証する。失敗は ValueError(→B)。"""
    with open(rules_path, encoding="utf-8") as f:
        doc = json.load(f)
    if not isinstance(doc, dict) or not isinstance(doc.get("rules"), list):
        raise ValueError("トップレベルに rules 配列がない")
    hook_rules = []
    for i, rule in enumerate(doc["rules"]):
        if not isinstance(rule, dict):
            raise ValueError(f"rules[{i}] がオブジェクトでない")
        layer = rule.get("layer")
        if layer not in ("permission", "hook", "advisory"):
            raise ValueError(f"rules[{i}] '{rule.get('id')}': layer が不正")
        if rule.get("action") not in ("deny", "ask"):
            raise ValueError(f"rules[{i}] '{rule.get('id')}': action が不正")
        if layer == "hook":
            if not rule.get("id"):
                raise ValueError(f"rules[{i}]: hook ルールに id がない")
            hook_rules.append(rule)
    return hook_rules


def evaluate(hook_rules: list, event: dict, project_dir: str) -> None:
    tool_name = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    is_bypass = detect_bypass(event)

    if os.environ.get("HARNESS_GUARD_DEBUG"):
        sys.stderr.write(
            "[harness-guard:debug] keys=%s tool=%s mode_detected=%s\n"
            % (sorted(event.keys()), tool_name,
               "bypass" if is_bypass else "normal/unknown"))

    matched_ask = None
    # 規約3: deny を先に全件評価(deny が ask に勝つ)
    for rule in hook_rules:
        if not rule_matches(rule, tool_name, tool_input, project_dir):
            continue
        if rule["action"] == "deny":
            deny("NEVER ルール違反 [{0}]: {1} — {2} "
                 "(定義: .claude/harness-rules.json。代替手段を検討するか、"
                 "人間に確認すること)".format(
                     rule["id"], rule.get("description", ""),
                     rule.get("reason", "")))
        elif matched_ask is None:
            matched_ask = rule

    if matched_ask is not None:
        rid = matched_ask["id"]
        desc = matched_ask.get("description", "")
        reason = matched_ask.get("reason", "")
        if is_bypass:
            deny("CONFIRM ルール [{0}]: {1} — この操作には人間の計画承認が"
                 "必要。自律実行(bypassPermissions)中のため操作を停止する。"
                 "作業を中断し、計画を提示して人間の承認を得ること。{2}".format(
                     rid, desc, reason))
        else:
            ask("CONFIRM ルール [{0}]: {1} — {2}".format(rid, desc, reason))

    no_decision()


# ---------------------------------------------------------------- main

def main() -> None:
    # 1) プロジェクトディレクトリの解決(stdin より先。env が一次情報源)
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or ""

    # 2) ルールファイルの所在確認を最優先で行う(規約2)
    #    env が無い場合の cwd フォールバックは stdin 解析後に再試行する
    rules_path = os.path.join(project_dir, RULES_REL_PATH) if project_dir else ""
    if rules_path:
        _STATE["rules_present"] = os.path.isfile(rules_path)

    # 3) stdin の解析。失敗時: ルール在り=クローズ / 所在不明・不在=オープン
    raw = sys.stdin.read()
    try:
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise ValueError("stdin がオブジェクトでない")
    except Exception as exc:
        if _STATE["rules_present"]:
            deny("[harness-guard] フック入力(stdin)を解析できないため、"
                 "安全のため操作を停止した。人間が確認すること。"
                 f"(詳細: {exc})")
        no_decision(f"stdin 解析失敗かつルールファイル所在不明のため素通り: {exc}")

    # 4) env が無かった場合のフォールバック(cwd → カレント)
    if not project_dir:
        project_dir = str(event.get("cwd") or "") or os.getcwd()
        rules_path = os.path.join(project_dir, RULES_REL_PATH)
        _STATE["rules_present"] = os.path.isfile(rules_path)

    # シナリオ A: 不在=オープン(/harness:init 未実施のプロジェクトを邪魔しない)
    if not _STATE["rules_present"]:
        no_decision("harness-rules.json が無いためルール強制は無効"
                    "(/harness:init 未実施)")

    # シナリオ B: 在るのに読めない/スキーマ不適合=クローズ
    try:
        hook_rules = load_rules(rules_path)
    except Exception as exc:
        deny("[harness-guard] .claude/harness-rules.json が破損または"
             "スキーマ不適合のため、安全のため操作を停止した。"
             f"人間が修復するまで自律動作を再開しないこと。(詳細: {exc})")

    evaluate(hook_rules, event, project_dir)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException as exc:  # シナリオ C: 準クローズ
        try:
            if _STATE["rules_present"]:
                deny("[harness-guard] 内部エラーのため安全側で操作を停止した"
                     f"({type(exc).__name__}: {exc})。人間が確認すること。")
            else:
                no_decision(f"初期化前エラーのため素通り: {exc}")
        except SystemExit:
            raise
        except BaseException:
            # 最終防衛線: stdout が死んでいても exit 2(公式ブロックコード)で塞ぐ
            try:
                print('{"hookSpecificOutput":{"hookEventName":"PreToolUse",'
                      '"permissionDecision":"deny","permissionDecisionReason":'
                      '"harness-guard fatal error (fail closed)"}}')
                sys.stdout.flush()
                sys.exit(0)
            except BaseException:
                sys.exit(2)
