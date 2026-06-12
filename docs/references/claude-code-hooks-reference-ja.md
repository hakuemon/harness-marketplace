# Claude Code Hooks 日本語リファレンス

公式8機構リファレンスの姉妹文書。Hooks の公式仕様を日本語で正準化する。

- 出典: Claude Code 公式ドキュメント「Hooks reference」 https://code.claude.com/docs/en/hooks
  および「How Claude remembers your project」 https://code.claude.com/docs/en/memory
- 確認日: 2026-06-12(Hooks はイベント数が頻繁に増えている。メジャー更新時に再確認すること)

## Hooks とは

ライフサイクルの決まった時点で**決定論的に**実行される、ユーザー定義のハンドラ。モデルが実行するか判断するのではなく、ハーネスが必ず実行する。CLAUDE.md や Auto memory は「コンテキスト(お願い)」であり、公式も「モデルの判断に関わらず行動をブロックしたいなら PreToolUse フックを使え」と明言している。

## 構造: 3階層

```
イベント(いつ) → マッチャーグループ(どの対象で) → ハンドラ(何を実行)
```

```json
{
  "hooks": {
    "PreToolUse": [                          ← イベント
      {
        "matcher": "Bash",                   ← マッチャー
        "hooks": [
          { "type": "command",
            "if": "Bash(rm *)",              ← 追加フィルタ(任意)
            "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/block-rm.sh" }
        ]
      }
    ]
  }
}
```

## 定義場所とスコープ

| 場所 | スコープ | 共有 |
|---|---|---|
| `~/.claude/settings.json` | 自分の全プロジェクト | しない |
| `.claude/settings.json` | 単一プロジェクト | リポジトリにコミット可 |
| `.claude/settings.local.json` | 単一プロジェクト | しない(gitignore) |
| 管理ポリシー設定 | 組織全体 | 管理者制御 |
| **プラグインの `hooks/hooks.json`** | プラグイン有効時 | **プラグインに同梱** ← meta-harness はここ |
| Skill / Agent のフロントマター | そのコンポーネントの稼働中のみ | コンポーネントファイル内 |

全ソースのフックは**マージされて全部発火**する(8機構表の通り)。

## 主要イベント(全29種から抜粋)

### 毎ツールコール(エージェントループ内)

| イベント | 発火タイミング | ブロック可否 |
|---|---|---|
| **PreToolUse** | ツール実行の直前 | **可** — NEVER 強制の主戦場 |
| PostToolUse | ツール成功の直後 | 不可(フィードバック注入は可) |
| PostToolUseFailure | ツール失敗の直後 | — |
| PostToolBatch | 並列ツール群の完了後、次のモデル呼び出し前 | — |
| PermissionRequest | 許可ダイアログ表示時 | 決定を返せる |

### 毎ターン

| イベント | 発火タイミング | 用途例 |
|---|---|---|
| UserPromptSubmit | プロンプト送信時、Claude が処理する前 | コンテキスト注入、入力検査 |
| **Stop** | Claude が応答を終えようとした時 | exit 2 / decision:"block" で**作業継続を強制**(終了ゲート)。ブロック条件は必ず解除可能にすること |
| StopFailure | API エラーでターンが終わった時 | 通知(出力は無視される) |

### セッション単位・その他

| イベント | 発火タイミング | 用途例 |
|---|---|---|
| SessionStart / SessionEnd | セッション開始・終了 | 立ち上がり手順の注入、後片付け |
| Setup | `--init-only` 等での起動時 | CI 用の一回限り準備 |
| SubagentStart / SubagentStop | サブエージェントの開始・終了 | v0.5 で関係 |
| InstructionsLoaded | CLAUDE.md / rules がロードされた時 | ロード監視 |
| FileChanged | 監視対象ファイルのディスク上の変更 | 設定ファイル改変の検知 |
| PreCompact / PostCompact | コンテキスト圧縮の前後 | チェックポイント |

(他: UserPromptExpansion, PermissionDenied, Notification, MessageDisplay, TaskCreated, TaskCompleted, TeammateIdle, ConfigChange, CwdChanged, WorktreeCreate/Remove, Elicitation 系, SessionEnd)

## マッチャーの評価規則

| matcher の値 | 評価方法 | 例 |
|---|---|---|
| `"*"`、`""`、省略 | 全マッチ | そのイベントの全発生で発火 |
| 英数字・`_`・`\|` のみ | 完全一致(`\|` 区切りリスト) | `Bash`、`Edit\|Write` |
| それ以外の文字を含む | JavaScript 正規表現 | `^Notebook`、`mcp__memory__.*` |

- ツール系イベントは `tool_name` に対してマッチする。MCP ツールは `mcp__<server>__<tool>` 形式
- `mcp__memory` は完全一致扱いになり何にもマッチしない。サーバー全体は `mcp__memory__.*` と書く(頻出の罠)
- イベントごとにマッチ対象が違う(SessionStart は起動種別、SubagentStop はエージェント種別、等)

## `if` フィルタ(ハンドラ単位の絞り込み)

permission rule 構文でツール名+引数を見て、ハンドラの起動自体を絞る。`"Bash(git *)"`、`"Edit(*.ts)"` など。

**重要な公式注記**: Bash の `if` 判定はベストエフォートで、コマンドがパースできない場合は**フェイルオープン**(フックは起動する)。さらに公式は「ハードな許可/拒否の強制には、フックではなく permission システムを使え」と明言している。→ 設計含意: 静的に書ける禁止は permissions の deny ルール、動的・条件付きの判定はフック、と使い分けるのが公式の意図。

## ハンドラ5タイプ

| type | 何が動くか | 用途 |
|---|---|---|
| `command` | シェルコマンド。stdin で JSON 入力、exit code と stdout で応答 | 機械判定の主力。最速・最も確実 |
| `http` | JSON を POST。レスポンスボディが応答 | 外部サービス連携。**エラー時は非ブロック**になる点に注意 |
| `mcp_tool` | 接続済み MCP サーバーのツールを呼ぶ | MCP 切断時は非ブロックエラー → ハード強制には不向き |
| `prompt` | 単発の LLM 評価。yes/no 決定を返す | 意味判定(v0.2.x 候補) |
| `agent` | Read/Grep 等を使えるサブエージェントで検証(実験的) | 高度な意味判定(将来) |

共通フィールド: `timeout`(command 等は既定600秒、prompt 30秒)、`async`(バックグラウンド)、`asyncRewake`(exit 2 で Claude を起こす)、`statusMessage`、`once`(スキルフロントマター限定)。

## command フックの2形式

- **exec form**(`args` あり): シェルを介さず直接 spawn。`${CLAUDE_PLUGIN_ROOT}` 等のプレースホルダが各引数に素のまま代入される。**プラグイン同梱スクリプトはこちらを推奨**(スペース・特殊文字のクォート問題が消える)
- **shell form**(`args` なし): `sh -c` 等で解釈。パイプや `&&` が必要な時だけ

```json
{ "type": "command", "command": "python3",
  "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/never-guard.py"] }
```

パスプレースホルダ: `${CLAUDE_PROJECT_DIR}`(プロジェクト)、`${CLAUDE_PLUGIN_ROOT}`(プラグイン)、`${CLAUDE_PLUGIN_DATA}`。環境変数としてもスクリプトに渡る。

## 入出力と判定の返し方

入力(stdin の JSON): `tool_name`, `tool_input`(file_path / command 等), `session_id`, `cwd` など。

**exit code の意味(最重要・事故多発ポイント)**:

| exit code | 意味 |
|---|---|
| 0(出力なし) | 「決定なし」— 通常の許可フローへ。**承認ではない** |
| **2** | ブロック(PreToolUse ならツール中止、Stop なら継続強制) |
| 1 | **非ブロックエラー — 処理は続行してしまう。** ポリシー強制に exit 1 を使うのは典型的バグ |

JSON での精密制御(PreToolUse は専用スキーマ、他イベントの多くはトップレベル `decision`):

```json
{ "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",        // "allow" | "deny" | "ask"
    "permissionDecisionReason": "NEVER ルール違反: ...",
    "updatedInput": { },                  // 入力の書き換えも可能
    "additionalContext": ""               // Claude へ渡す追加文脈
} }
```

`"ask"` を返すと許可ダイアログに送れる → **CONFIRM ルールの機械化に使える**。

## セキュリティ・運用上の注意

- フックは**自分の権限で動く任意コード**。配布元を信頼できないフックはレビュー必須
- 同期実行なのでマッチした全ツールコールに遅延が乗る。ゲート系フックは高速に保つ(目安: 数百ms以内)
- 組織管理者は `allowManagedHooksOnly` でユーザー/プロジェクト/プラグインのフックを無効化できる(管理マーケットプレイス経由の配布は例外)

## Auto memory(関連機構・公式仕様)

- Claude が自分で書くノート。場所は `~/.claude/projects/<project>/memory/`(git リポジトリ単位)
- `MEMORY.md` がインデックスとしてセッション開始時にロードされ(先頭約200行)、トピックファイルは必要時にオンデマンドで読まれる
- 保存場所は `autoMemoryDirectory`(settings.json、任意スコープ)で変更可。プロジェクト内に向ければコミット・共有可能(ワークスペース信頼ダイアログの承認が必要)
- 無効化: `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`
- 公式の位置づけ: CLAUDE.md と同じく「コンテキストであって強制ではない」。強制は Hooks の役割
