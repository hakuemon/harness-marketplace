#!/usr/bin/env python3
"""harness-verify.py — ハーネス生成物の整合検証(/harness:verify の判定エンジン)

仕様: harness-verify-spec-draft.md v1(2026-07-02 確定)
- サブコマンド: check(デフォルト・読取専用)。render / template は Step 2 で追加
- 終了コード: 0=全緑(または未導入) / 2=所見あり / 3=内部エラー
- exit 1 は意図的に不使用(未捕捉例外のカナリア。main が全例外を 3 に変換する)
- 依存: Python 3 標準ライブラリのみ
"""

import argparse
import difflib
import json
import re
import sys
import traceback
from pathlib import Path

# ---------------------------------------------------------------------------
# 定数(マーカー文字列の正準はテンプレート側。ここは同一文字列を再現する)
# ---------------------------------------------------------------------------

SECTION_NAMES = ("never-enforced", "never-advisory", "confirm-machine")

RULES_JSON_REL = Path(".claude") / "harness-rules.json"
RULES_MD_REL = Path("docs") / "claude" / "rules.md"
SETTINGS_REL = Path(".claude") / "settings.json"
SETTINGS_LOCAL_REL = Path(".claude") / "settings.local.json"
GITFLOW_REL = Path("docs") / "claude" / "git-flow.md"

GIT_RULE_IDS = ("no-direct-push-to-base", "no-merge-on-manual")
MERGE_MODE_ROW = re.compile(r"^\|\s*\*\*MERGE_MODE\*\*\s*\|\s*([^|]+?)\s*\|", re.M)

VALID_LAYERS = ("permission", "hook", "advisory")
VALID_ACTIONS = ("deny", "ask")

LAYER_TAG = {"permission": "L1 permission", "hook": "L2 hook", "advisory": "advisory"}

EMPTY_SECTION_PLACEHOLDER = "(該当ルールなし)"


def begin_marker(name: str) -> str:
    return (
        f"<!-- BEGIN GENERATED: {name} — "
        f"source: .claude/harness-rules.json — DO NOT EDIT -->"
    )


def end_marker(name: str) -> str:
    return f"<!-- END GENERATED: {name} -->"


# ---------------------------------------------------------------------------
# 所見(findings)
# ---------------------------------------------------------------------------

class Finding:
    def __init__(self, code: str, target: str, message: str, diff: str = ""):
        self.code = code
        self.target = target
        self.message = message
        self.diff = diff

    def as_text(self) -> str:
        line = f"[{self.code}] {self.target}: {self.message}"
        if self.diff:
            line += "\n" + self.diff
        return line

    def as_dict(self) -> dict:
        d = {"code": self.code, "target": self.target, "message": self.message}
        if self.diff:
            d["diff"] = self.diff
        return d


# ---------------------------------------------------------------------------
# 排他3分割(仕様 §3)
# ---------------------------------------------------------------------------

def section_of(rule: dict):
    """ルールが属する節名を返す。どの節にも属さなければ None(幽霊ルール)。

    定義(排他であることは構成から保証される):
      never-enforced  = action:deny ∧ layer∈{permission,hook}
      never-advisory  = layer:advisory(action 不問)
      confirm-machine = action:ask ∧ layer:hook
    """
    layer = rule.get("layer")
    action = rule.get("action")
    if layer == "advisory":
        return "never-advisory"
    if action == "deny" and layer in ("permission", "hook"):
        return "never-enforced"
    if action == "ask" and layer == "hook":
        return "confirm-machine"
    return None


# ---------------------------------------------------------------------------
# レンダラ f(仕様 §3)— 決定的・純関数
# ---------------------------------------------------------------------------

def _fmt_match(match: dict) -> str:
    parts = []
    if "tool" in match:
        parts.append(f"tool=`{match['tool']}`")
    if "path_glob" in match:
        parts.append(f"path=`{match['path_glob']}`")
    if "command_regex" in match:
        parts.append(f"regex=`{match['command_regex']}`")
    return " / ".join(parts)


def render_rule(rule: dict) -> str:
    lines = [f"- **{rule['id']}** [{LAYER_TAG[rule['layer']]}]: {rule['description']}"]
    if rule["layer"] == "permission":
        lines.append("  - deny: " + ", ".join(f"`{d}`" for d in rule["deny"]))
    elif rule["layer"] == "hook":
        lines.append(f"  - 対象: {_fmt_match(rule['match'])}")
    if rule.get("reason"):
        lines.append(f"  - 理由: {rule['reason']}")
    if rule.get("note"):
        lines.append(f"  - 注記: {rule['note']}")
    return "\n".join(lines)


def render_sections(doc: dict) -> dict:
    """f(harness-rules.json) → {節名: 本文テキスト}。

    - 並び順は JSON 配列順を保存(ソートしない)
    - 空節は明示プレースホルダ
    - 本文は正規化済み(LF・行末空白なし・本文自体は末尾改行を含まない。
      ファイル上の改行はマーカー行との結合時に与えられる)
    """
    buckets = {name: [] for name in SECTION_NAMES}
    for rule in doc.get("rules", []):
        name = section_of(rule)
        if name is not None:
            buckets[name].append(render_rule(rule))
    return {
        name: ("\n".join(items) if items else EMPTY_SECTION_PLACEHOLDER)
        for name, items in buckets.items()
    }


# ---------------------------------------------------------------------------
# check A: harness-rules.json の構造健全性(仕様 §2)
# ---------------------------------------------------------------------------

def check_a(doc: dict, skip_placeholder_regex: bool = False) -> list:
    findings = []
    rules = doc.get("rules")
    if not isinstance(rules, list):
        findings.append(Finding("A-FIELD", "harness-rules.json",
                                "トップレベルに rules 配列がない"))
        return findings

    seen_ids = {}
    for idx, rule in enumerate(rules):
        target = rule.get("id") or f"rules[{idx}]"

        # --- A-FIELD: 必須フィールド ---
        missing = [k for k in ("id", "action", "layer") if not rule.get(k)]
        if missing:
            findings.append(Finding("A-FIELD", target,
                                    f"必須フィールド欠落: {', '.join(missing)}"))

        # --- A-DUP: id 重複(v0.2.2 で実例発生・PR #8 で解消) ---
        rid = rule.get("id")
        if rid:
            if rid in seen_ids:
                findings.append(Finding(
                    "A-DUP", rid,
                    f"同一 id のルールが複数存在(rules[{seen_ids[rid]}] と rules[{idx}])"))
            else:
                seen_ids[rid] = idx

        # --- A-ENUM ---
        layer = rule.get("layer")
        action = rule.get("action")
        enum_ok = True
        if layer and layer not in VALID_LAYERS:
            findings.append(Finding("A-ENUM", target,
                                    f"layer が不正: {layer!r}(許容: {', '.join(VALID_LAYERS)})"))
            enum_ok = False
        if action and action not in VALID_ACTIONS:
            findings.append(Finding("A-ENUM", target,
                                    f"action が不正: {action!r}(許容: {', '.join(VALID_ACTIONS)})"))
            enum_ok = False

        # --- 層別の必須構造(A-FIELD / A-MATCH / A-REGEX) ---
        if layer == "permission":
            deny = rule.get("deny")
            if not isinstance(deny, list) or not deny:
                findings.append(Finding("A-FIELD", target,
                                        "permission 層に deny 配列がない(または空)"))
        elif layer == "hook":
            match = rule.get("match")
            if not isinstance(match, dict):
                findings.append(Finding("A-FIELD", target, "hook 層に match がない"))
            else:
                if not match:
                    findings.append(Finding(
                        "A-MATCH", target,
                        "match が空(全ツール全操作 deny の DoS になる — レビュー指摘6)"))
                else:
                    if not match.get("tool"):
                        findings.append(Finding("A-MATCH", target, "match.tool がない"))
                    if "command_regex" not in match and "path_glob" not in match:
                        findings.append(Finding(
                            "A-MATCH", target,
                            "command_regex / path_glob のいずれも無い"))
                    regex = match.get("command_regex")
                    if regex is not None and not (
                            skip_placeholder_regex and "{{" in regex):
                        try:
                            re.compile(regex)
                        except re.error as exc:
                            findings.append(Finding(
                                "A-REGEX", target,
                                f"command_regex がコンパイル不能: {exc}"))

        # --- A-ORPHAN(enum が健全なルールに限り判定 — 重複所見を避ける) ---
        if enum_ok and layer in VALID_LAYERS and action in VALID_ACTIONS:
            if section_of(rule) is None:
                findings.append(Finding(
                    "A-ORPHAN", target,
                    f"どの節にも属さない幽霊ルール(action={action}, layer={layer}: "
                    "強制も表示もされない)"))

    return findings


# ---------------------------------------------------------------------------
# check B: rules.md ドリフト(仕様 §2)
# ---------------------------------------------------------------------------

def extract_section(md_lines: list, name: str):
    """マーカー間の本文を行リストで返す。異常はメッセージ文字列を返す。"""
    begin, end = begin_marker(name), end_marker(name)
    begin_idxs = [i for i, l in enumerate(md_lines) if l == begin]
    end_idxs = [i for i, l in enumerate(md_lines) if l == end]

    if len(begin_idxs) > 1 or len(end_idxs) > 1:
        return None, "マーカーが重複している"
    if not begin_idxs and not end_idxs:
        return None, "BEGIN/END マーカーが存在しない"
    if not begin_idxs:
        return None, "BEGIN マーカーが欠落(END のみ存在)"
    if not end_idxs:
        return None, "END マーカーが欠落(BEGIN のみ存在)"
    if end_idxs[0] < begin_idxs[0]:
        return None, "END マーカーが BEGIN より前にある"
    return md_lines[begin_idxs[0] + 1:end_idxs[0]], None


def check_b(doc: dict, rules_md_path: Path) -> list:
    findings = []
    if not rules_md_path.exists():
        return [Finding("B-MARKER", str(rules_md_path), "rules.md が存在しない")]

    md_lines = rules_md_path.read_text(encoding="utf-8").split("\n")
    expected = render_sections(doc)

    for name in SECTION_NAMES:
        actual_lines, err = extract_section(md_lines, name)
        if err:
            findings.append(Finding("B-MARKER", name, err))
            continue
        actual = "\n".join(actual_lines)
        if actual != expected[name]:
            diff = "\n".join(difflib.unified_diff(
                actual.split("\n"), expected[name].split("\n"),
                fromfile=f"rules.md:{name}(実ファイル)",
                tofile=f"f(harness-rules.json):{name}(期待値)",
                lineterm=""))
            findings.append(Finding(
                "B-DRIFT", name,
                "生成節が f(harness-rules.json) と不一致(下記 diff 参照)", diff))
    return findings


# ---------------------------------------------------------------------------
# check C: settings.json ↔ L1 ルールの整合(仕様 §2)— 厳密な集合一致
# ---------------------------------------------------------------------------

def check_c(doc: dict, settings_path: Path) -> list:
    expected = []
    for rule in doc.get("rules", []):
        if rule.get("layer") == "permission":
            for entry in rule.get("deny") or []:
                if entry not in expected:
                    expected.append(entry)

    if not settings_path.exists():
        if expected:
            return [Finding("C-MISSING", str(settings_path),
                            f"settings.json が存在しない(L1 の期待 deny {len(expected)} 件が未適用)")]
        return []

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [Finding("C-PARSE", str(settings_path),
                        f"settings.json がパース不能: {exc}")]

    actual = data.get("permissions", {}).get("deny", [])
    findings = []
    missing = [e for e in expected if e not in actual]
    extra = [a for a in actual if a not in expected]
    if missing:
        findings.append(Finding(
            "C-MISSING", "settings.json permissions.deny",
            "L1 ルールの deny が settings.json に無い(保護が効いていない): "
            + ", ".join(f"`{m}`" for m in missing)))
    if extra:
        findings.append(Finding(
            "C-EXTRA", "settings.json permissions.deny",
            "harness-rules.json に対応する permission 層ルールが無い deny(単一情報源違反。"
            "まず JSON に permission 層ルールとして書くのが正): "
            + ", ".join(f"`{e}`" for e in extra)))
    return findings


# ---------------------------------------------------------------------------
# check D: MERGE_MODE 整合(仕様 §2)— git-flow.md の値 ↔ ルールの有無
# ---------------------------------------------------------------------------

def check_d(doc: dict, gitflow_path: Path) -> list:
    rules = doc.get("rules", [])
    merge_rule_count = sum(1 for r in rules if r.get("id") == "no-merge-on-manual")
    git_rules_present = any(r.get("id") in GIT_RULE_IDS for r in rules)

    if not gitflow_path.exists():
        if git_rules_present:
            return [Finding("D-ADOPT", str(gitflow_path),
                            "git-flow.md が無いのに git 系ルール("
                            + ", ".join(r.get("id") for r in rules
                                        if r.get("id") in GIT_RULE_IDS)
                            + ")が存在する(採用状態の不整合)")]
        return []  # git-flow 未採用 → N/A

    text = gitflow_path.read_text(encoding="utf-8")
    m = MERGE_MODE_ROW.search(text)
    if not m:
        return [Finding("D-MODE", str(gitflow_path),
                        "MERGE_MODE 行(| **MERGE_MODE** | <値> |)が見つからない")]
    mode = m.group(1).strip()

    if mode == "manual":
        if merge_rule_count == 1:
            return []
        if merge_rule_count == 0:
            return [Finding("D-MODE", "MERGE_MODE",
                            "manual なのに no-merge-on-manual ルールが無い"
                            "(マージの安全装置が効いていない)")]
        return [Finding("D-DUP", "no-merge-on-manual",
                        f"manual だが no-merge-on-manual が {merge_rule_count} 件ある"
                        "(A-DUP と同根。ちょうど1件が正)")]
    if mode == "auto":
        if merge_rule_count == 0:
            return []
        return [Finding("D-MODE", "MERGE_MODE",
                        f"auto なのに no-merge-on-manual ルールが {merge_rule_count} 件ある"
                        "(自律マージが deny される)")]
    return [Finding("D-MODE", "MERGE_MODE",
                    f"不正な値: {mode!r}(許容: manual / auto)")]


# ---------------------------------------------------------------------------
# check E: 運用ゲートの機械化可能分(仕様 §2)
# ---------------------------------------------------------------------------

def check_e(root: Path) -> list:
    local_path = root / SETTINGS_LOCAL_REL
    if not local_path.exists():
        return [Finding("E-LOCAL", str(local_path),
                        "settings.local.json が存在しない(clone 直後は再生成が必要 — "
                        "内容は人間が作成する。init SKILL.md 参照)")]
    try:
        data = json.loads(local_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [Finding("E-PARSE", str(local_path),
                        f"settings.local.json がパース不能: {exc}")]

    amd = data.get("autoMemoryDirectory")
    if amd is None:
        return []  # 機能未使用とみなす(所見なし)
    findings = []
    amd_path = Path(amd)
    if not amd_path.is_absolute():
        findings.append(Finding("E-MEMPATH", "autoMemoryDirectory",
                                f"絶対パスでない: {amd!r}"))
    elif not amd_path.is_dir():
        findings.append(Finding("E-MEMPATH", "autoMemoryDirectory",
                                f"指すディレクトリが実在しない: {amd}"))
    return findings




def run_check(root: Path, as_json: bool) -> int:
    rules_json_path = root / RULES_JSON_REL
    rules_md_path = root / RULES_MD_REL

    # 未導入 → 正常報告で exit 0(未 init プロジェクトを邪魔しない)
    if not rules_json_path.exists():
        report(as_json, status="not-installed", findings=[],
               message=f"未導入: {rules_json_path} が存在しない。/harness:init を参照")
        return 0

    # JSON 破損 → 所見(それを報告するのが verify の仕事)
    try:
        doc = json.loads(rules_json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        findings = [Finding("A-PARSE", str(rules_json_path),
                            f"harness-rules.json がパース不能: {exc}")]
        report(as_json, status="findings", findings=findings)
        return 2

    findings = (check_a(doc)
                + check_b(doc, rules_md_path)
                + check_c(doc, root / SETTINGS_REL)
                + check_d(doc, root / GITFLOW_REL)
                + check_e(root))

    if findings:
        report(as_json, status="findings", findings=findings)
        return 2
    report(as_json, status="ok", findings=[],
           message="全チェック緑(A: 構造 / B: rules.md / C: settings / "
                   "D: MERGE_MODE / E: 運用ゲート)")
    return 0


def report(as_json: bool, status: str, findings: list, message: str = ""):
    if as_json:
        payload = {"status": status,
                   "findings": [f.as_dict() for f in findings]}
        if message:
            payload["message"] = message
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if message:
        print(message)
    for f in findings:
        print(f.as_text())
    if findings:
        print(f"\n所見 {len(findings)} 件")


# ---------------------------------------------------------------------------
# render サブコマンド(仕様 §5)— 唯一の書込操作。対象は rules.md のマーカー間のみ
# ---------------------------------------------------------------------------

def run_render(root: Path, dry_run: bool) -> int:
    rules_json_path = root / RULES_JSON_REL
    rules_md_path = root / RULES_MD_REL

    if not rules_json_path.exists():
        report(False, status="not-installed", findings=[],
               message=f"未導入: {rules_json_path} が存在しない。/harness:init を参照")
        return 0
    try:
        doc = json.loads(rules_json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        report(False, status="findings",
               findings=[Finding("A-PARSE", str(rules_json_path),
                                 f"harness-rules.json がパース不能: {exc}")])
        return 2

    # 前提条件1: check A 全緑(不正な JSON からは描画しない)
    a_findings = check_a(doc)
    if a_findings:
        report(False, status="findings", findings=a_findings,
               message="render 中止: check A に所見があるため描画しない")
        return 2

    # 前提条件2: マーカー対が健全であること
    if not rules_md_path.exists():
        report(False, status="findings",
               findings=[Finding("B-MARKER", str(rules_md_path),
                                 "rules.md が存在しない(render は既存マーカー対に"
                                 "流し込む。初期生成は /harness:init の領分)")])
        return 2
    original = rules_md_path.read_text(encoding="utf-8")
    md_lines = original.split("\n")

    marker_findings = []
    spans = {}
    for name in SECTION_NAMES:
        body_lines, err = extract_section(md_lines, name)
        if err:
            marker_findings.append(Finding("B-MARKER", name, err))
        else:
            begin_idx = md_lines.index(begin_marker(name))
            end_idx = md_lines.index(end_marker(name))
            spans[name] = (begin_idx, end_idx, body_lines)
    if marker_findings:
        report(False, status="findings", findings=marker_findings,
               message="render 中止: マーカー対が不健全なため何も書かない")
        return 2

    # マーカー間のみを差し替える(散文=マーカー外には一切触れない)
    expected = render_sections(doc)
    changed = []
    for name in sorted(spans, key=lambda n: spans[n][0], reverse=True):
        begin_idx, end_idx, body_lines = spans[name]
        expected_lines = expected[name].split("\n")
        if body_lines != expected_lines:
            changed.append(name)
            md_lines[begin_idx + 1:end_idx] = expected_lines

    if not changed:
        print("変更なし: 全生成節は f(harness-rules.json) と一致済み")
        return 0

    new_text = "\n".join(md_lines)
    if dry_run:
        print(f"--dry-run: 書込は行わない。更新対象の節: {', '.join(sorted(changed))}")
        diff = "\n".join(difflib.unified_diff(
            original.split("\n"), new_text.split("\n"),
            fromfile="rules.md(現状)", tofile="rules.md(render 後)", lineterm=""))
        print(diff)
        return 0

    rules_md_path.write_text(new_text, encoding="utf-8")
    print(f"render 完了: 更新した節: {', '.join(sorted(changed))}")
    return 0


# ---------------------------------------------------------------------------
# template サブコマンド(仕様 §7)— marketplace CI 用のテンプレート lint
# ---------------------------------------------------------------------------

def run_template(file: str, expect_rules) -> int:
    path = Path(file)
    if not path.exists():
        report(False, status="findings",
               findings=[Finding("A-PARSE", file, "ファイルが存在しない")])
        return 2
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        report(False, status="findings",
               findings=[Finding("A-PARSE", file, f"パース不能: {exc}")])
        return 2

    # プレースホルダ {{...}} は文字列として許容。id 一意性はプレースホルダ込みで判定
    findings = check_a(doc, skip_placeholder_regex=True)

    if expect_rules is not None:
        actual = len(doc.get("rules", []))
        if actual != expect_rules:
            findings.append(Finding(
                "T-COUNT", file,
                f"ルール数が期待と不一致: 期待 {expect_rules} / 実際 {actual}"))

    if findings:
        report(False, status="findings", findings=findings)
        return 2
    n = len(doc.get("rules", []))
    print(f"テンプレート lint 緑({n} ルール)")
    return 0


# ---------------------------------------------------------------------------
# main(全例外 → exit 3。exit 1 経路ゼロ)
# ---------------------------------------------------------------------------

class _Parser(argparse.ArgumentParser):
    """使用法エラーを exit 3 に寄せる(argparse 既定の exit 2 は「所見あり」と衝突)。"""

    def error(self, message):
        self.print_usage(sys.stderr)
        print(f"エラー: {message}", file=sys.stderr)
        sys.exit(3)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="harness-verify.py",
        description="ハーネス生成物の整合検証(読取専用がデフォルト)")
    sub = parser.add_subparsers(dest="command")
    p_check = sub.add_parser("check", help="整合チェック(デフォルト・読取専用)")
    p_check.add_argument("--root", default=".", help="プロジェクトルート(省略時 cwd)")
    p_check.add_argument("--json", action="store_true", help="所見を JSON で出力")
    p_render = sub.add_parser("render", help="rules.md の生成節を f(JSON) で再生成")
    p_render.add_argument("--root", default=".", help="プロジェクトルート(省略時 cwd)")
    p_render.add_argument("--dry-run", action="store_true",
                          help="書込せず diff を印字")
    p_template = sub.add_parser("template",
                                help="テンプレート lint(marketplace CI 用)")
    p_template.add_argument("file", help="harness-rules.json.template のパス")
    p_template.add_argument("--expect-rules", type=int, default=None,
                            help="期待ルール数(不一致で所見)")
    return parser


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith("-"):
        argv = ["check"] + argv  # デフォルトサブコマンド
    args = build_parser().parse_args(argv)
    if args.command == "render":
        return run_render(Path(args.root), args.dry_run)
    if args.command == "template":
        return run_template(args.file, args.expect_rules)
    return run_check(Path(args.root), args.json)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        traceback.print_exc()
        sys.exit(3)
