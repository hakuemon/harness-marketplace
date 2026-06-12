# meta-harness

ハーネスエンジニアリングの共通基盤を配布するプラグインマーケットプレイス。

## 構造

```
harness-marketplace/
├── .claude-plugin/
│   └── marketplace.json          # マーケットプレイスカタログ(配布の入口)
└── plugins/
    └── harness/                  # プラグイン本体(共通・不変層)
        ├── .claude-plugin/
        │   └── plugin.json       # プラグインマニフェスト(version がここにある)
        └── skills/
            └── init/             # /harness:init として呼び出される
                ├── SKILL.md      # initializer の手順書
                └── templates/    # 生成物の雛形(プロジェクト固有・可変層の源)
```

## インストール(ローカル検証)

リポジトリを clone またはこのフォルダを配置した上で、Claude Code 内で:

```
/plugin marketplace add ./harness-marketplace
/plugin install harness@meta-harness
```

GitHub にホストする場合(プライベートリポジトリ可):

```
/plugin marketplace add <github-user>/harness-marketplace
/plugin install harness@meta-harness
```

## スモークテスト

1. **インストール確認**: `/plugin` でプラグイン一覧に harness v0.1.0 が表示されること
2. **新規プロジェクト経路**: 空のディレクトリで Claude Code を起動し `/harness:init` を実行。
   Phase 0(調査)→ Phase 1(インタビュー)→ Phase 2(生成)→ Phase 3(レポート)が順に進み、
   CLAUDE.md と docs/claude/ 配下 4 ファイルが生成されること
3. **既存プロジェクト経路**: ハーネス整備済みプロジェクト(例: Dashboard)で `/harness:init` を実行。
   いきなり生成せず、既存ファイルの検出結果と移行計画の提示で止まること
4. **ハーネスの効果確認**: 生成後、**新しいセッション**を開始して簡単なタスクを依頼し、
   ルールが参照されることを確認(CLAUDE.md はセッション開始時に読み込まれるため)

## アップデートの流れ

1. テンプレートやスキルを修正する
2. `plugin.json` と `marketplace.json` の `version` を上げる(例: 0.1.0 → 0.1.1)
   ※ version を明示している場合、これを上げない限り利用者に更新が配信されない
3. GitHub に push する
4. 各環境で `/plugin marketplace update meta-harness` を実行する

## ロードマップ

- **v0.1**(現在): initializer スキルのみ。生成物の検証が目的
- **v0.2**: NEVER ルール強制エンジン — PreToolUse フックがプロジェクト側の
  ルール定義ファイルを読んで判定する方式(ルール=プロジェクト側、エンジン=プラグイン側)
- **v0.3**: 運用サイクルのスキル化(/harness:plan, /harness:report)
- **v0.4**: /harness:update — 逸脱ログを読み、テンプレート新版との差分を提案するマイグレーションスキル
- **v0.5**: レビュー・検証サブエージェントの同梱
# harness-marketplace
