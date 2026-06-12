# harness-marketplace

ハーネスエンジニアリングの共通基盤を配布するプラグインマーケットプレイス。

## 実行形態の前提

一次対象は**対話セッション + bypassPermissions**(人間が起動・指示し、Claude がターン内を自律走行、ガードレールが実行中を守る。サブスクリプション枠内で完結)。`claude -p` / Agent SDK は Stage 4(完全自律)の任意オプション — 2026-06-15 以降は独立した Agent SDK クレジット課金の対象のため、採用は技術判断かつコスト判断。

## 動作要件

- WSL2 / Linux(検証環境: WSL2 Ubuntu)
- `python3` が PATH にあること(L2 ルール強制エンジンの実行に必要。不在時は L1+advisory のみで動作)

## 構造

```
harness-marketplace/
├── .claude-plugin/marketplace.json    # 配布カタログ
└── plugins/harness/                   # プラグイン本体(共通・不変層)
    ├── .claude-plugin/plugin.json     # version 0.2.0
    ├── hooks/hooks.json               # PreToolUse: 編集系 + Bash で harness-guard を起動
    ├── scripts/harness-guard.py       # ルール強制エンジン(Python3 標準ライブラリのみ)
    └── skills/init/                   # /harness:init
        ├── SKILL.md
        └── templates/                 # 生成物の雛形(プロジェクト固有・可変層の源)
```

## v0.2 の中核: 三層強制モデル

| 層 | 手段 | 生成・所在 |
|---|---|---|
| L1 | permissions の deny(bypass 貫通) | init が `.claude/settings.json` に生成 |
| L2 | harness-guard.py(全許可モードで発火) | プラグイン同梱。プロジェクトの `.claude/harness-rules.json` を実行時に読む |
| L3 | prompt/agent フック(意味判定) | 未実装(v0.2.x 検討)。該当ルールは advisory |

ルールは `action`(deny=NEVER / ask=CONFIRM)×`layer` の二軸。CONFIRM はモード対応: 通常モード=確認ダイアログ / bypassPermissions=**deny+停止指示**(自律実行は人間の承認が要る操作で停止し、計画を提示して終わる)。

失敗時挙動: ルールファイル**不在=オープン**(未導入プロジェクトを邪魔しない)/ **破損=クローズ** / 内部エラー=準クローズ。詳細は設計書 rev.2 参照。

> **脅威モデル**: このエンジンが守るのは誠実なエージェントの逸脱・ミス・コンテキスト喪失。悪意ある迂回(シェル経由のファイル書き換え等)への防御は sandbox / OS レベル隔離の領域(フェーズ成熟度 3〜4 で検討)。

## インストール

```
/plugin marketplace add <github-user>/harness-marketplace   # or ローカルパス
/plugin install harness@meta-harness                        # user scope 推奨
```

導入後、各プロジェクトで `/harness:init` を実行(新規構築・既存移行の両対応)。

## スモークテスト(v0.2 受け入れ基準)

1. **L1 貫通**: bypassPermissions 中に `.claude/harness-rules.json` の Edit が deny されること
2. **L2 NEVER**: `git push --force` が通常・bypass の両モードでブロックされ、理由が表示されること
3. **L2 CONFIRM**: 対象パス編集が、通常=ダイアログ / bypass=deny+停止報告になること
4. **入力仕様**: `HARNESS_GUARD_DEBUG=1` で stdin に許可モードキーが含まれることを確認(含まれない場合はモード検出の代替設計に差し戻し)
5. **失敗時挙動**: ファイル不在→警告のみで続行 / JSON 破損→deny
6. **性能**: 追加遅延が数百 ms 以内(コンテナ実測: 約 22ms/call)
7. **Auto memory**: 信頼承認後、`docs/claude/memory/` に MEMORY.md が生成されること
8. (参考)bypass 中の ask の素の挙動を記録

## アップデートの流れ

1. 修正 → `plugin.json` と `marketplace.json` の version を上げる(上げないと配信されない)
2. push → 各環境で `/plugin marketplace update meta-harness`

## ロードマップ

- **v0.1**: initializer スキル(完了)
- **v0.2**(現在): NEVER/CONFIRM ルール強制エンジン+Auto memory 運用(`docs/claude/memory/`、コミット対象)
- **v0.3**: 運用サイクルのスキル化(/harness:plan, /harness:report)+ Stop フック終了ゲート(申し送り: ①ゲート条件は運用スキルの完了定義から導出 ②対話/自律でモード分岐 ③ループ防止と解除経路 ④checklist×git status 照合)
- **v0.4**: /harness:update(逸脱ログを読んでテンプレート新版との差分を提案)
- **v0.5**: レビュー・検証サブエージェント
- 方針のみ: Agent teams(並列サブエージェントで限界が来たら再検討)
