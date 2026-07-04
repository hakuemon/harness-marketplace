# MIGRATION: v0.2.2 → v0.3

対象: v0.2.2 以前の `/harness:init` で構築済みのプロジェクト。
v0.3 の変更は**プラグイン側**(verify スクリプト追加・テンプレート形式変更)であり、エンジン(harness-guard.py)・ルール形式(harness-rules.json)・settings 系は**無変更**。移行作業は rules.md のマーカー差し替えのみ。

## v0.3 で何が変わったか

1. **`/harness:verify` の追加**: 生成物の整合検証(check)・rules.md 生成節の決定的再生成(render)・テンプレート lint(template)
2. **維持フローの契約変更**: rules.md の再生成は「Claude に依頼」→「`harness-verify.py render` の実行」に置換。生成節は文字通り f(harness-rules.json) の出力になり、`check` がドリフトを機械検出する
3. **rules.md のマーカー形式変更**: 生成節が BEGIN/END マーカー対で区画化された(旧: 開始コメント1行のみ)

## 移行手順

### 1. プラグインを v0.3.0 に更新する

マーケットプレイスの通常のアップデート手順(README 参照)。更新後、新しいセッションで `/hooks` のフック実在を確認する。

### 2. rules.md のマーカーを差し替える(人間が編集)

`docs/claude/rules.md` の生成節 3 箇所について、旧形式の開始コメント行を BEGIN 行に置き換え、節の本文(ルール箇条書き)の直後に END 行を追加する。

| 節 | 旧(この行を置換) | 新 |
|---|---|---|
| NEVER 強制 | `<!-- GENERATED FROM .claude/harness-rules.json (action=deny, layer=permission\|hook) — DO NOT EDIT -->` | `<!-- BEGIN GENERATED: never-enforced — source: .claude/harness-rules.json — DO NOT EDIT -->` |
| NEVER advisory | `<!-- GENERATED FROM .claude/harness-rules.json (layer=advisory) — DO NOT EDIT -->` | `<!-- BEGIN GENERATED: never-advisory — source: .claude/harness-rules.json — DO NOT EDIT -->` |
| CONFIRM 機械化 | `<!-- GENERATED FROM .claude/harness-rules.json (action=ask) — DO NOT EDIT -->` | `<!-- BEGIN GENERATED: confirm-machine — source: .claude/harness-rules.json — DO NOT EDIT -->` |

END 行(各節の本文の直後、次の散文・見出しの前に追加):

```
<!-- END GENERATED: never-enforced -->
<!-- END GENERATED: never-advisory -->
<!-- END GENERATED: confirm-machine -->
```

END 行の位置がずれても、この時点の本文は次の render で全置換されるため神経質になる必要はない。ただし**散文(Bash 注記・モード別実効性の表・CONFIRM 規約)をマーカー内に含めない**こと — マーカー内は render のたびに f(harness-rules.json) で上書きされる。

### 3. render を実行して生成節を同期する

```bash
python3 <プラグインルート>/scripts/harness-verify.py render --root <プロジェクトルート> --dry-run   # まず diff 確認
python3 <プラグインルート>/scripts/harness-verify.py render --root <プロジェクトルート>             # 問題なければ本実行
```

旧生成節は Claude の手描画だったため、内容が正しくても**表現差による diff が必ず出る**。これは想定どおり(以後この表現が正準になる)。

### 4. check で全緑を確認する

```bash
python3 <プラグインルート>/scripts/harness-verify.py check --root <プロジェクトルート>
```

`全チェック緑` / exit 0 を確認。所見が出た場合はコードごとの意味と修復者を `/harness:verify`(skills/verify/SKILL.md)の表で確認する。

### 5. deviation-log.md に記録する

移行日・プラグイン版・rules.md の diff 概要(表現差の全置換である旨)を記録して完了。

## 互換性の注記

- **エンジン・フック・ルール形式・settings 系は無変更**。移行前後で強制挙動(L1/L2)は 1 bit も変わらない
- 移行手順 2〜4 を実施するまで `check` は B-MARKER / B-DRIFT の所見を出すが、これは移行未完了の正しい検出であり実害はない(強制層は動き続けている)
- git-flow 採用プロジェクトは、`docs/claude/git-flow.md` の MERGE_MODE 切替手順 step 3 の文言(rules.md 再生成の手段)を新テンプレートに合わせて更新しておくとよい(任意。実挙動には影響しない)
