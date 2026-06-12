# meta-harness v0.2 設計案 — NEVER ルール強制エンジン + Auto memory 運用

ステータス: 壁打ち用ドラフト(未承認)
前提文書: claude-code-8-mechanisms.md / claude-code-hooks-reference-ja.md
作成日: 2026-06-12

## ゴール

1. NEVER ルールを「お願い(プロンプト指示)」から「強制(機械的ブロック)」に昇格させる
2. ルール定義(プロジェクト固有)と強制エンジン(プラグイン共通)を分離し、エンジン改善が全プロジェクトに伝播する構造にする
3. Auto memory をテンプレートの運用サイクルに組み込み、セッション跨ぎのナレッジ蓄積を仕組み化する

## 強制の三層モデル

公式仕様の調査から、強制手段は1つではなく3つあることが判明した。強さと柔軟さのトレードオフで使い分ける。

| 層 | 手段 | 強さ | 表現力 | v0.2 での扱い |
|---|---|---|---|---|
| L1 | **permissions の deny ルール**(.claude/settings.json) | 最強(公式がハード強制に推奨) | 静的パターンのみ(ツール+パス/コマンド) | **実装** — /harness:init が生成 |
| L2 | **command フックエンジン**(プラグイン同梱、PreToolUse) | 強(決定論的) | 動的。プロジェクトのルールファイルを読んで任意ロジックで判定 | **実装** — v0.2 の本体 |
| L3 | prompt / agent フック(LLM 判定) | 中(モデル判定が入る) | 意味的ルール(「@theme {} ブロックを変更しない」等) | **延期**(v0.2.x で検討) |

設計原理: 各ルールを表現できる**最も上の層**に置く。L1 で書けるものを L2 に置かない(速度と確実性で損)。L2 で書けないものだけ L3 に送る。

## 論点1への回答: 機械判定できないルールの扱い

ルール定義に `enforcement` フィールドを持たせ、ルール自身がどの層で強制されるかを宣言する。

- `"permission"` → L1。init が settings.json の deny に変換
- `"hook"` → L2。エンジンが実行時に判定
- `"advisory"` → 強制なし。rules.md(プロンプト層)にのみ存在。意味的ルールは当面ここに置き、L3 実装後に昇格

これにより「機械判定できないルールがあるから強制エンジンは作れない」という全か無かの問題が消える。守れるものから守り、守れないものは明示的に advisory と宣言して可視化する。

## 論点2への回答: 情報源の一元化

**`.claude/never-rules.json` を正(source of truth)とする。**

- 根拠1: 目標4の原則「agent-readable が源泉、human-readable は描画結果」と一致
- 根拠2: Anthropic のハーネス記事の知見 — エージェントに守らせる構造化データは Markdown より JSON が改変されにくい
- rules.md の NEVER 節は JSON から**生成**する(手書きしない)。CONFIRM ルールと advisory ルールの散文は rules.md に直接書いてよい
- 乖離防止: rules.md の NEVER 節に「このセクションは never-rules.json から生成。直接編集禁止」と明記

### CONFIRM ルールの機械化(オプション)

PreToolUse の `permissionDecision: "ask"` を使うと、CONFIRM ルールも「該当操作で必ず許可ダイアログを出す」形に機械化できる。v0.2 ではスキーマに `"confirm"` enforcement を予約だけして、実装は運用してから判断する。

## ルールスキーマ案(.claude/never-rules.json)

```json
{
  "$schema": "https://example.com/never-rules.schema.json",
  "version": 1,
  "rules": [
    {
      "id": "protect-claude-rules",
      "description": "ハーネス定義ファイルを削除・改変から守る",
      "enforcement": "permission",
      "deny": ["Edit(docs/claude/rules.md)", "Write(docs/claude/rules.md)"]
    },
    {
      "id": "no-force-push",
      "description": "force push の禁止",
      "enforcement": "hook",
      "match": { "tool": "Bash", "command_regex": "git\\s+push\\s+.*(--force|-f)\\b" },
      "reason": "履歴破壊の防止。必要な場合は人間が手動で実行する"
    },
    {
      "id": "protect-tailwind-theme",
      "description": "Tailwind v4 の @theme {} ブロックを変更しない",
      "enforcement": "advisory",
      "note": "ファイル内領域の判定が必要。L3(prompt フック)実装後に昇格候補"
    }
  ]
}
```

## エンジン実装方針(プラグイン側)

```
plugins/harness/
├── hooks/
│   └── hooks.json          ← PreToolUse: matcher "Edit|Write|MultiEdit" と "Bash"
└── scripts/
    └── never-guard.py      ← エンジン本体
```

- hooks.json は **exec form** でスクリプトを指定: `"command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/never-guard.py"]`
- エンジンの動作:
  1. stdin の JSON から `tool_name` / `tool_input` を読む
  2. `${CLAUDE_PROJECT_DIR}/.claude/never-rules.json` をロード
  3. `enforcement: "hook"` のルールに対して照合
  4. 違反 → `permissionDecision: "deny"` + `permissionDecisionReason` に**ルール id と理由**を返す(Claude が理由を読んで方針修正できる)
  5. 非違反 → exit 0(決定なし。通常の許可フローへ)
- **フェイルオープン方針(要議論)**: never-rules.json が存在しない/壊れている場合は exit 0 + stderr に警告。init 未実施のプロジェクトでプラグインが邪魔をしないため。ただし「壊せば無効化できる」穴になるため、対策として never-rules.json 自身を守る permission deny ルールを init が必ず生成する(L1 が L2 の土台を守る構造)
- exit 1 をポリシー強制に使わない(非ブロックエラーで素通りする — 公式明記の典型バグ)

## Auto memory の組み込み

関与レベルは「導線+運用規約」(機構自体は公式ビルトイン。テンプレが作るのは設定と規約)。

### 役割分担の定義(operation.md テンプレートに追記)

| 記録 | 書き手 | 性質 | 優先度 |
|---|---|---|---|
| 逸脱ログ(deviation-log.md) | 人間(壁打ちで決定) | 意思決定の正準記録 | **正** |
| Auto memory(MEMORY.md ほか) | Claude(作業中に自動) | 作業知見の生データ | 参考 |

矛盾したら逸脱ログが勝つ。Auto memory に**繰り返し現れる**知見は CLAUDE.md またはテンプレート更新の議題に昇格する(公式トリガー表「同じ修正を2回したら CLAUDE.md へ」の Auto memory 版)。

### 運用サイクルへの接続(目標2のフィードバックループ強化)

テンプレート更新の壁打ちに持ち込む入力を2系統に定義する:
1. 各プロジェクトの逸脱ログ(人間の判断記録)
2. 各プロジェクトの MEMORY.md(Claude の学習記録)

### 保存場所(要議論)

デフォルトは `~/.claude/projects/<project>/memory/` でリポジトリ外(コミットされない)。`autoMemoryDirectory` でプロジェクト内に移せばコミット・共有可能になるが、信頼ダイアログ承認が必要+ノイズがコミット履歴に入る。**v0.2 提案: デフォルト位置のまま運用観察し、共有の必要が生じた時点で再判断**(ソロ運用の現状では移す動機が弱い)。

## v0.2 成果物一覧

| 成果物 | 場所 | 新規/変更 |
|---|---|---|
| never-guard.py(エンジン) | プラグイン scripts/ | 新規 |
| hooks.json | プラグイン hooks/ | 新規 |
| never-rules.json スキーマ+生成ロジック | init スキルに追加 | 変更 |
| rules.md テンプレート(NEVER 節を生成式に) | init テンプレート | 変更 |
| operation.md テンプレート(Auto memory 規約) | init テンプレート | 変更 |
| 既存プロジェクト移行手順(rules.md → never-rules.json) | init スキルの既存経路 | 変更 |
| plugin.json version 0.2.0 | プラグイン | 変更 |

## 未決事項(壁打ち議題)

1. フェイルオープン or フェイルクローズ(上記提案: オープン+L1で土台保護)
2. CONFIRM の "ask" 機械化を v0.2 に含めるか(提案: スキーマ予約のみ)
3. Auto memory の保存場所(提案: デフォルト維持)
4. エンジン言語: Python か Bash か(提案: Python。JSON 処理と正規表現が安全に書ける。実行環境に python3 を仮定できるかが論点)
5. Stop フック(終了ゲート: チェックリスト未更新なら終了をブロック等)を v0.2 に含めるか、運用スキル化する v0.3 に回すか(提案: v0.3)
