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
    ├── .claude-plugin/plugin.json     # version 0.2.1
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
| L3 | prompt/agent フック(意味判定) | 未実装(検討中)。該当ルールは advisory |

ルールは `action`(deny=NEVER / ask=CONFIRM)×`layer` の二軸。CONFIRM はモード対応: 通常モード=確認ダイアログ / bypassPermissions=**deny+停止指示**(自律実行は人間の承認が要る操作で停止し、計画を提示して終わる)。

**ask の実効性(v0.2 実機検証):** 主戦場は **auto/acceptEdits モードでの割り込み**(自動承認中に本来出ないダイアログを出す)と **bypass での停止変換**。通常モードでは標準確認に紛れて区別できない。

失敗時挙動: ルールファイル**不在=オープン**(未導入プロジェクトを邪魔しない)/ **破損=クローズ** / 内部エラー=準クローズ。詳細は設計書 rev.2 参照。

> **脅威モデル**: このエンジンが守るのは誠実なエージェントの逸脱・ミス・コンテキスト喪失。v0.2.1 で「**誠実なフォールバック迂回**」(編集ツール失敗時に Bash の `>>`/`sed -i` 等へ自然に流れる経路 — 実機で実証)を明示的に守備範囲へ追加し、companion ルールで塞いだ。ただし regex はヒューリスティック(`cd` 後の相対パス・変数展開・インタプリタ経由の書込は拾えない)。意図的・回避的な迂回への防御は sandbox / OS レベル隔離の領域(フェーズ成熟度 3〜4 で検討)。

## v0.2.1 の変更点

1. **固定 companion ルール `protect-harness-files-bash`**: ハーネス定義ファイル(harness-rules.json / settings*.json)への Bash 経由書込(`>` `>>` / `tee` / `sed -i` / `cp` / `mv` / `rm` / `truncate` / `touch` / `dd` / `ln`)を deny。エンジン変更なし(ルール定義のみで実現)
2. **プロジェクト固有 path_glob ルールへの companion 提案**: /harness:init が「Bash 書込ガードも付けるか」をルールごとに確認(勝手に増やさない)
3. **rules.md テンプレ更新**: 「Bash 経由でも同じ(編集ツール失敗時に Bash で代替しない)」の散文 NEVER と、ask のモード別実効性の注記を組み込み
4. **検証手順の更新**: セッション再起動後に `/hooks` でプラグイン由来フックの実在を確認するゲートを追加(インストール/更新直後はフックがロードされないことがある — 実機で確認)

## v0.2.2 の変更点

1. **git-flow スキル**(`skills/git-flow/`): 実装完了タスクを規約に従って自律出荷(ブランチ→コミット→push→PR)する。発動の錨は checklist のタスク完了。**PR まで自律 / マージは MERGE_MODE(auto / manual)で分岐**(manual では PR が人間のレビューゲート)。教育層であり、強制は harness-rules.json が担う二段構え(追加フックや settings.json 改変は不要)
2. **init の git-flow 統合**: /harness:init が採用可否と規約値(base ブランチ・TYPE 語彙・MERGE_MODE 等)を確認し、`docs/claude/git-flow.md`(規約値)と 2 ルール(`no-direct-push-to-base`=base 直 push を deny / `no-merge-on-manual`=MERGE_MODE=manual 時に `gh pr merge` を deny)を生成する。**安全側デフォルト = manual**(auto 移行は人間がルールを削除)。git 管理外プロジェクトではスキップ。base 上 commit は教育層に委ね、追加フック・settings.json 改変は不要
3. **エンジンのテスト資産**(`tests/`): harness-guard.py の pytest 回帰テスト 33 ケース(終了経路の不変条件・deny 優先・path 両形照合・companion 真陽性/偽陽性・失敗時 A/B/C 等)+ GitHub Actions CI(py3.10/3.12)。エンジン改修時の回帰を自動検出

## v0.3 の変更点

- **`/harness:verify` を追加**(設計レビュー指摘2への対応): 生成物の整合検証。`check`(A: harness-rules.json 構造 / B: rules.md ドリフト / C: settings↔L1 整合 / D: MERGE_MODE 整合 / E: 運用ゲート)・`render`(rules.md 生成節の決定的再生成)・`template`(テンプレート lint、CI 組込済)
- **決定的レンダラ**: rules.md の生成節は文字通り f(harness-rules.json) の出力になり、「JSON が正・md は描画結果」が機械保証に格上げされた。維持フローの「Claude に再生成を依頼」は「render 実行」に置換
- **終了コード規約**: verify は 0(緑)/ 2(所見)/ 3(内部エラー)。**exit 1 はリポジトリ全域で意図的に不使用**(未知のクラッシュ経路のカナリア)
- **既存プロジェクトの移行**: [docs/MIGRATION-0.2.2-to-0.3.md](docs/MIGRATION-0.2.2-to-0.3.md)(rules.md のマーカー差し替え+初回 render のみ)
- 設計記録: [docs/design/harness-verify-spec.md](docs/design/harness-verify-spec.md)

## インストール

```
/plugin marketplace add <github-user>/harness-marketplace   # or ローカルパス
/plugin install harness@meta-harness                        # user scope 推奨
```

導入後、各プロジェクトで `/harness:init` を実行(新規構築・既存移行の両対応)。

**インストール/更新後は必ず: セッションを再起動 → `/hooks` で PreToolUse に harness@meta-harness 由来のフック 2 件(編集系・Bash)が見えることを確認**してから運用・テストを開始する。

## スモークテスト(v0.2.x 受け入れ基準)

0. **フック実在**: 再起動後、`/hooks` にプラグイン由来の 2 エントリがあること(無ければ再起動・再インストール)
1. **L1 貫通**: bypassPermissions 中に `.claude/harness-rules.json` の Edit が deny されること
2. **L2 NEVER**: `git push --force` が通常・bypass の両モードでブロックされ、理由が表示されること
3. **L2 CONFIRM**: 対象パス編集が、auto/acceptEdits=割り込みダイアログ / bypass=deny+停止報告になること(通常モードでは標準確認と区別不能のため判定不可)
4. **入力仕様**: bypass 中の CONFIRM が「自律実行中のため停止」の専用文言で deny されること(=モード検出が機能している実証)
5. **失敗時挙動**: ファイル不在→警告のみで続行 / JSON 破損→deny(人間修復→回復まで一周確認)
6. **性能**: 追加遅延が数百 ms 以内(実測: コンテナ 約22ms / WSL2 約28ms per call)
7. **Auto memory**: 信頼承認後、`docs/claude/memory/` に MEMORY.md が生成されること(自然発生しない場合は明示的な記録依頼で誘発可)
8. **Bash companion(v0.2.1)**: `echo x >> .claude/settings.json` の実行依頼が deny されること。`cat .claude/harness-rules.json` と `git checkout .claude/harness-rules.json` は素通りすること(誤発動なし)
9. (参考)bypass 中の ask の素の挙動を記録

> 検証ノウハウ: CLAUDE.md/rules.md を読んだ Claude は該当操作をツール呼び出し前に自主拒否することがある(プロンプト層の正常動作)。バックストップの検証には「スモークテストであり、ブロックされるのが期待結果」と明示して実行を試みさせる。

## アップデートの流れ

1. 修正 → `plugin.json` と `marketplace.json` の version を上げる(上げないと配信されない)
2. push → 各環境で `/plugin marketplace update meta-harness`
3. セッション再起動 → `/hooks` でフック実在確認(スモークテスト #0)

**v0.2.0 で init 済みのプロジェクトへの適用:** `.claude/harness-rules.json` は人間編集のため、`protect-harness-files-bash` ルール(templates/harness-rules.json.template 参照)を**人間が手動で追記**し、rules.md の生成節を再生成する。または /harness:init を再実行して移行差分の提示を受ける。

## ロードマップ

- **v0.1**: initializer スキル(完了)
- **v0.2**: NEVER/CONFIRM ルール強制エンジン+Auto memory 運用(**実機スモークテスト合格 2026-06-12**)
- **v0.2.1**: スモークテストの発見への対応 — Bash 書込 companion(固定+提案制)、ask モード依存性の文書化、フック実在確認ゲート
- **v0.2.2**(現在): git-flow スキル(自律出荷・MERGE_MODE 分岐)+ init 統合、エンジンのテスト資産(pytest 33 + CI)。強制は harness-rules.json の 2 ルールに集約(エンジン無変更・追加フック不要)
- **v0.3**: 運用サイクルのスキル化(/harness:plan, /harness:report)+ Stop フック終了ゲート(申し送り: ①ゲート条件は運用スキルの完了定義から導出 ②対話/自律でモード分岐 ③ループ防止と解除経路 ④checklist×git status 照合)
- **v0.4**: /harness:update(逸脱ログを読んでテンプレート新版との差分を提案)
- **v0.5**: レビュー・検証サブエージェント
- L3(prompt/agent フック): advisory ルールと「regex に拾えない Bash 迂回」の昇格先として検討
- 方針のみ: Agent teams(並列サブエージェントで限界が来たら再検討)
