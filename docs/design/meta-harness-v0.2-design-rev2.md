# meta-harness v0.2 設計書 rev.2 — ルール強制エンジン + Auto memory 運用

ステータス: **承認済み設計**(未決事項5件の壁打ち完了。実装着手可)
前提文書: claude-code-8-mechanisms.md / claude-code-hooks-reference-ja.md
作成日: 2026-06-12(rev.1: 同日ドラフト → rev.2: 5論点の決定+実行形態の前提を反映)

## ゴール

1. NEVER ルールを「お願い(プロンプト指示)」から「強制(機械的ブロック)」に昇格させる
2. CONFIRM ルールを「実行時バックストップ」として機械化する(Plan mode 承認規約の代替ではなく補完)
3. ルール定義(プロジェクト固有)と強制エンジン(プラグイン共通)を分離し、エンジン改善が全プロジェクトに伝播する構造にする
4. Auto memory を運用サイクルに組み込み、セッション跨ぎのナレッジ蓄積を仕組み化する

## 実行形態の前提(rev.2 追加)

**一次対象: 対話セッション + bypassPermissions。** 人間がセッションを起動して指示し、Claude がターン内を自律走行、ガードレールが実行中を守り、終了後に人間がレビューする形態。サブスクリプション利用枠内で完結する。

- `claude -p` / Agent SDK / GitHub Actions は **Stage 4(完全自律)の任意オプション**と位置づける。2026-06-15 以降これらは独立した Agent SDK クレジット枠の課金対象となるため、採用は技術判断かつコスト判断となる
- v0.2〜v0.5 のロードマップは `-p` に依存しない
- Stop フック(v0.3)は対話の自律セッションを一次ターゲットとして設計する

**bypass 下で確認済みの公式仕様**(設計の土台):

| 仕様 | 含意 |
|---|---|
| permissions の deny はモード適用より先に評価され、bypass でもブロックする | L1 は bypass を貫通する唯一の静的防壁 |
| フックは全許可モードで発火し、deny / exit 2 はモードに関係なく効く | L2 エンジンは bypass 運用の定石パターンそのもの |
| 現行の bypass は .claude 等の保護パスへの書き込みプロンプトもスキップする | ルールファイルの自己保護は L1 deny で行うしかない(標準保護は当てにしない) |

## 強制の三層モデル

| 層 | 手段 | 強さ | v0.2 での扱い |
|---|---|---|---|
| L1 | permissions の deny(.claude/settings.json) | 最強(モードより上位) | **実装** — /harness:init が生成 |
| L2 | command フックエンジン(プラグイン同梱、PreToolUse) | 強(決定論的・全モード発火) | **実装** — v0.2 の本体 |
| L3 | prompt / agent フック(LLM 判定) | 中(意味的ルール用) | **延期**(v0.2.x で検討) |

設計原理: 各ルールを表現できる最も上の層に置く。L1 で書けるものを L2 に置かない。L2 で書けないものだけ L3 へ送る(それまでは advisory)。

## ルールの二軸スキーマ(論点2の決定)

ルールは「何が起きるか(action)」と「どこで強制するか(layer)」の直交2軸で宣言する。

| | layer: permission (L1) | layer: hook (L2) | layer: advisory |
|---|---|---|---|
| **action: deny**(NEVER) | 静的パターンの deny | エンジンが deny | rules.md の散文のみ |
| **action: ask**(CONFIRM) | **使用しない**(bypass 下の挙動が不定) | **モード対応**(下記) | rules.md の散文のみ(従来の CONFIRM) |

### CONFIRM のモード対応(L2)

エンジンは stdin の許可モードを読み、CONFIRM ルール該当時に応答を切り替える:

| 実行モード | エンジンの応答 |
|---|---|
| 通常モード(人間が監督) | `ask` → ダイアログでその場確認 |
| bypassPermissions(自律実行) | `deny` + 理由「CONFIRM ルール {id}: 人間の計画承認が必要。停止して計画を提示し承認を得ること」 |

- 意味論: CONFIRM =「人間がループに入るべき操作」。監督下ではダイアログ、自律実行では**停止+報告**に翻訳される。エージェントは deny 理由を読めるため、「黙って失敗」ではなく「CONFIRM 対象のため停止した。計画はこうだ」という報告で終われる
- **ask はPlan mode 承認の代替ではない**。計画レビューの儀式は operation.md の規約(プロンプト層)が引き続き担い、ask/deny はそれをすり抜けた場合の実行時バックストップである。この二段構えを rules.md テンプレートに明記する
- **ダイアログ疲れ対策**: 機械化(ask)する CONFIRM は特に重要な 2〜3 個まで。残りは散文 CONFIRM に留める。このガイドを interview.md に記載し、「ダイアログを反射的に承認していないか」を運用観察項目に追加する

## ルールファイル仕様

**`.claude/harness-rules.json` を正(source of truth)とする。**

> rev.2 命名変更: CONFIRM ルールも格納するため `never-rules.json` から改名(「never」では内容を表せない)。エンジンも `harness-guard.py` とする。

- rules.md の NEVER / CONFIRM(機械化分)節は JSON から**生成**する(手書き禁止と節内に明記)
- advisory ルールと散文 CONFIRM は rules.md に直接書いてよい
- 根拠: 「agent-readable が源泉、human-readable は描画結果」原則+構造化データは Markdown より改変されにくいという Anthropic ハーネス記事の知見

```json
{
  "version": 1,
  "rules": [
    {
      "id": "protect-harness-files",
      "description": "ハーネス定義ファイルを改変から守る",
      "action": "deny",
      "layer": "permission",
      "deny": [
        "Edit(.claude/harness-rules.json)", "Write(.claude/harness-rules.json)",
        "Edit(.claude/settings.json)",      "Write(.claude/settings.json)"
      ]
    },
    {
      "id": "no-force-push",
      "description": "force push の禁止",
      "action": "deny",
      "layer": "hook",
      "match": { "tool": "Bash", "command_regex": "git\\s+push\\s+\\S*\\s*(--force|-f)\\b" },
      "reason": "履歴破壊の防止。必要な場合は人間が手動で実行する"
    },
    {
      "id": "confirm-db-migration",
      "description": "DB マイグレーションの作成・変更は計画承認後に行う",
      "action": "ask",
      "layer": "hook",
      "match": { "tool": "Edit|Write", "path_glob": "**/db/migration/**" },
      "reason": "スキーマ変更は影響が大きい。Plan mode で計画を提示し承認を得ること"
    },
    {
      "id": "protect-tailwind-theme",
      "description": "Tailwind v4 の @theme {} ブロックを変更しない",
      "action": "deny",
      "layer": "advisory",
      "note": "ファイル内領域の判定が必要。L3 実装後に hook へ昇格候補"
    }
  ]
}
```

`protect-harness-files` は init が**必ず**生成する固定ルール(削除・改名も不可と init スキルに明記)。

## 失敗時挙動(論点1の決定)

| シナリオ | 状況 | 挙動 | 理由 |
|---|---|---|---|
| A | harness-rules.json 不在 | **オープン**(exit 0 + stderr 警告) | init 未実施のプロジェクトで日常作業を壊さない(プラグインは user scope で常時有効) |
| B | 存在するが破損(JSON エラー・スキーマ不適合) | **クローズ**(deny + 「破損。人間が修復するまで停止」) | 在るのに読めないのは事故か改変。自律動作を止めて人間が介入すべき異常 |
| C | エンジン内部エラー | **準クローズ**(ファイル所在確認後の例外は deny に変換) | 大域 try/except で捕捉し、exit 1 への自然落下を構造的に排除 |
| D | セッション中のルールファイル改変・削除 | **L1 で予防**(protect-harness-files) | エンジン側では防げないため、L1 が L2 の土台を守る |

注: B の帰結として、壊れた JSON を Claude 自身に修復させることはできない(Edit が deny されるため)。修復は人間の仕事 — これは欠点ではなく仕様。

### 脅威モデル(明記)

この強制エンジンが守るのは「**誠実なエージェントの逸脱・ミス・コンテキスト喪失**」である。Bash を広く許可された悪意あるエージェントは理論上 L1+L2 を迂回できる(シェル経由のファイル書き換え等。Bash の完全な静的解析は不可能)。能動的な攻撃への防御は sandbox 実行・Bash 許可の制限・OS レベル隔離の領域であり、フェーズ成熟度 3〜4 で検討する。「フックがあるから完全に安全」とは考えないこと。

## エンジン実装仕様(論点4の決定)

```
plugins/harness/
├── hooks/
│   └── hooks.json          ← PreToolUse: matcher "Edit|Write|MultiEdit" と "Bash"
└── scripts/
    └── harness-guard.py    ← エンジン本体
```

- **言語: Python 3、標準ライブラリのみ**(json / re / sys / os / fnmatch)。pip 依存ゼロは絶対条件(プラグイン可搬性)
- hooks.json は **exec form**: `{ "type": "command", "command": "python3", "args": ["${CLAUDE_PLUGIN_ROOT}/scripts/harness-guard.py"] }`
- 動作フロー(rev.2.1 で順序を明確化 — 旧記述は stdin 読取りを先に書いており、解析失敗時の挙動が曖昧だった):
  1. `${CLAUDE_PROJECT_DIR}/.claude/harness-rules.json` の**所在確認を最初に**行う(不在→シナリオ A)
  2. stdin JSON から `tool_name` / `tool_input` / 許可モード を読む(解析失敗かつルールファイル在り→**クローズ(deny)**。ルールが在る限り、読めない入力を素通りさせない)
  3. ルールファイルをロード+軽量スキーマ検証(破損・不適合→シナリオ B。layer / action の誤記は黙殺=ルール失効ではなく deny)
  4. `layer: "hook"` のルールを照合(Bash は command_regex、編集系は path_glob。**path は絶対・プロジェクト相対の両形に照合**し、相対パス入力のすり抜けを防ぐ)
  5. **deny を全件先に評価し、次に ask**(同一操作が両方に該当したら deny が勝つ)
  6. action: deny 違反 → `permissionDecision: "deny"` + ルール id と理由
  7. action: ask 該当 → モード対応(通常= ask / bypass = deny + 停止指示)
  8. 非該当 → exit 0(決定なし。承認ではない)
- **実装規約**(コードコメントにも明記):
  - main 全体を大域 try/except で包む。終了経路は「exit 0」と「stdout に判定 JSON」の**2つだけ**(最終防衛線として stdout 自体が書けない場合のみ、公式ブロックコード **exit 2** に落とす。exit 1 への経路は構造的に持たない)
  - exit 1 への自然落下を構造的に排除(非ブロックエラーで素通りする公式仕様のため)
  - ゲートは高速に保つ(目安: 数百 ms 以内。ファイル I/O は rules 1 回のみ)
- **ランタイム検証**: /harness:init の Phase 0 に python3 存在確認を追加。不在なら警告して L2 を保留(L1 と advisory のみで構成)。動作要件(WSL2 / Linux、python3)を README に明記

## Auto memory の組み込み(論点3の決定)

**`autoMemoryDirectory` を `docs/claude/memory/` に設定し、コミット対象とする。** init が .claude/settings.json に生成する。

```
docs/claude/
├── rules.md            ← 人間+生成(JSON から描画)
├── operation.md
├── checklist.md
├── deviation-log.md    ← 人間が書く意思決定の正準記録
└── memory/             ← Claude が書く学習記録(MEMORY.md + トピックファイル)
```

- 狙い: ①自律実行中の学習が git diff に乗り**監査証跡**になる ②成果レビューで MEMORY.md の diff を見て**誤学習を早期発見**できる ③壁打ちへの2系統入力(逸脱ログ+MEMORY.md)の収集コストがゼロになる
- 役割分担(operation.md テンプレートに記載):

| 記録 | 書き手 | 性質 | 優先度 |
|---|---|---|---|
| deviation-log.md | 人間(壁打ちで決定) | 意思決定の正準記録 | **正** |
| memory/(MEMORY.md ほか) | Claude(作業中に自動) | 作業知見の生データ | 参考 |

  矛盾したら逸脱ログが勝つ。memory に繰り返し現れる知見は CLAUDE.md / テンプレート更新の議題へ昇格
- トレードオフと運用: コミットノイズが過多なら「プロジェクト内+gitignore」へ後退可(設定 1 行)。まず全コミットで観察
- **信頼ダイアログ**: プロジェクト settings.json の autoMemoryDirectory はワークスペース信頼の承認後に有効。init の完了手順に「信頼承認 → その後に自律実行を開始」を明記(未承認のまま無人運転に入ると設定が効かない)
- worktree 注記: プロジェクト内配置は worktree ごとに分岐しブランチ経由でマージされる。単一 worktree 運用の現状では実害なし。Agent teams 採用時に再検討

## v0.2 成果物一覧

| 成果物 | 場所 | 新規/変更 |
|---|---|---|
| harness-guard.py(エンジン) | プラグイン scripts/ | 新規 |
| hooks.json | プラグイン hooks/ | 新規 |
| harness-rules.json スキーマ+生成ロジック | init スキル | 変更 |
| settings.json 生成(L1 deny + autoMemoryDirectory) | init スキル Phase 2 | 変更 |
| python3 存在確認 | init スキル Phase 0 | 変更 |
| rules.md テンプレート(NEVER/CONFIRM 節を生成式に+二段構えの明記) | init テンプレート | 変更 |
| operation.md テンプレート(Auto memory 規約+運用観察項目) | init テンプレート | 変更 |
| interview.md(ask 機械化は 2〜3 個までのガイド) | init テンプレート | 変更 |
| 既存プロジェクト移行手順(rules.md → harness-rules.json) | init スキル | 変更 |
| README(動作要件: WSL2/Linux + python3、実行形態の前提) | マーケットプレイス | 変更 |
| plugin.json / marketplace.json version 0.2.0 | 両マニフェスト | 変更 |

## スモークテスト項目

1. **L1 貫通確認**: bypassPermissions 中に harness-rules.json / settings.json の Edit が deny されること
2. **L2 NEVER**: `git push --force` が通常モードと bypass の両方でブロックされ、理由が Claude に表示されること
3. **L2 CONFIRM**: マイグレーションパス編集が、通常モードでダイアログ・bypass で deny+停止報告になること
4. **入力仕様の実証**: PreToolUse の stdin に許可モードが含まれることを確認(含まれない場合はモード検出の代替手段を設計に差し戻し)
5. **失敗時挙動**: ファイル不在→警告のみで続行 / JSON 破損→deny(クローズ)
6. **性能**: エンジンの追加遅延を計測(目標: 数百 ms 以内)
7. **Auto memory**: 信頼承認後、docs/claude/memory/ に MEMORY.md が生成されること
8. (参考)bypass 中の ask の素の挙動を記録(設計では使わないが仕様把握のため)

## v0.3 への申し送り(論点5: Stop フック終了ゲート)

1. ゲート条件は v0.3 運用スキル(/harness:report 等)の完了定義から導出する(規約を先に、強制を後に)
2. 対話モードと自律実行で挙動を分ける(stdin のモード・起動種別で判別)。Stop は「毎ターン終了」で発火するため、素朴な実装は対話セッションを壊す
3. ループ防止: stop_hook_active 相当のフラグ確認+ブロック回数の上限。ブロック条件には必ず解除経路を用意する
4. 検査対象の第一候補: checklist.md の更新有無と git status の照合

## 改訂履歴

- rev.1(2026-06-12): 初版ドラフト。三層モデル、論点1・2への仮回答、未決事項5件
- rev.2(2026-06-12): 壁打ちによる5論点の確定を反映。実行形態の前提(対話+bypass 一次、-p は Stage 4 オプション)を追加。スキーマを action × layer の二軸に改訂。CONFIRM をモード対応 L2 に一本化。Auto memory を docs/claude/memory/ に変更。ファイル名を harness-rules.json / harness-guard.py に変更。脅威モデル・スモークテスト・v0.3 申し送りを追加
- rev.2.1(2026-06-12): エンジン動作フローの曖昧さを修正(所在確認を stdin 解析より先に/stdin 破損+ルール在り=クローズ/deny は ask に優先/path は絶対・相対両形に照合/スキーマ誤記は黙殺せず deny)。stdout 書込不能時の最終防衛線として exit 2 を明文化。契機: フォールバックセッションのドラフト実装が旧記述の文言通りに実装した結果、解析失敗時フェイルオープン等の差異が生じたため(差分テストで実証)
