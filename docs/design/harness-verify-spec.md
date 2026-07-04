# harness-verify.py 仕様書(v1 確定 — 2026-07-02 壁打ちセッション)

> 全設計論点決着済み。未決は §10-4(バージョンピン照合 = v1 見送り・調査後再判断)のみで、実装を妨げない。

| 項目 | 内容 |
|---|---|
| 位置 | `plugins/harness/scripts/harness-verify.py`(harness-guard.py と同格の単体スクリプト) |
| 依存 | Python 3 標準ライブラリのみ。pytest 対象・CI 乗せ可 |
| 呼び出し | `/harness:verify` スキル(実行+日本語解説+人間確認チェックリスト印字)。スクリプト単体でも実行可 |
| 原則 | **デフォルトは読取専用**。書込は `render` サブコマンドのみ、対象は rules.md のマーカー間のみ。修復は行わない(検出+案内。例外は §5 の render) |

## 決定済み前提(このセッションで確定)

- **B-ii(決定的レンダラ)**: rules.md 生成節 ≡ f(harness-rules.json)。verify は同じ f で期待値を再計算し実ファイルとバイト比較
- **(a)**: 同一スクリプト・サブコマンド分離(`check` デフォルト / `render`)
- **(b)**: 出力仕様6判断(BEGIN/END マーカー対・ルール描画形式・match 生値含む・配列順保存・排他3分割・空節プレースホルダ)+正規化(UTF-8・LF・末尾改行1・行末空白なし)

---

## 1. CLI

```
harness-verify.py [check]  [--root DIR] [--json]        # デフォルト。読取専用
harness-verify.py render   [--root DIR] [--dry-run]     # rules.md 生成節を再生成
harness-verify.py template FILE [--expect-rules N]      # テンプレート lint(marketplace CI 用)
```

- `--root`: プロジェクトルート(省略時 cwd)。`.claude/harness-rules.json` の存在で導入判定
- `--json`: 所見を機械可読 JSON で出力(CI・スキル層のパース用)。人間向けテキストが既定

### 終了コード(確定 2026-07-02)

| code | 意味 |
|---|---|
| 0 | 全チェック緑(または「未導入」の正常報告) |
| 2 | 所見あり |
| 3 | 内部エラー(スクリプト自身の欠陥・予期しない例外) |

**exit 1 は意図的に不使用**。採用根拠(2026-07-02 確定):
1. **誤用時フェイルクローズ**: 本リポジトリの生態系では exit 2=ブロック / exit 1=非ブロック素通り(hook プロトコル)。将来 verify がフック文脈に誤流用されても、所見=exit 2 なら止まる方向に倒れる
2. **exit 1 のカナリア化**: Python の未捕捉例外は exit 1。main が全例外を exit 3 に変換する体制下では、exit 1 の観測=「エラーハンドラをすり抜けた未知のクラッシュ経路」と一意に確定する
3. **機械検証可能**: 「ソースに sys.exit(1) 不在」+「異常系 subprocess が 3 を返す」を自動テスト化でき、エンジンの exit-1-ゼロと同形式の不変条件になる

**実装要件**: main は最上位 try/except で全例外を捕捉し exit 3 に変換する(トレースバックは隠さず印字)。

### 所見フォーマット

1所見1行: `[<チェックID>-<コード>] <対象>: <メッセージ>`
例: `[B-DRIFT] never-enforced: 生成節が f(harness-rules.json) と不一致(下記 diff 参照)`
B の不一致には unified diff を添付する。

---

## 2. チェック定義

### A: harness-rules.json の構造健全性

入力: `.claude/harness-rules.json`

| コード | 判定 |
|---|---|
| A-DUP | 同一 id のルールが2件以上(※ v0.2.2 で実例発生・PR #8 で解消) |
| A-FIELD | 必須フィールド欠落(id / action / layer、permission 層は deny 配列、hook 層は match) |
| A-ENUM | layer ∉ {permission, hook, advisory} または action ∉ {deny, ask} |
| A-MATCH | hook 層の match が空、または tool 欠落、または command_regex / path_glob のいずれも無い(match:{} は全 deny DoS になる — レビュー指摘6) |
| A-REGEX | command_regex が re.compile 不能 |
| A-ORPHAN | 排他3分割のどの節にも属さないルール(幽霊ルール: 強制も表示もされない) |

補足: エンジン(load_rules)は寛容なまま(フェイルセーフ哲学)。厳密検証は verify の責務、という層分担。エンジン側の強化(指摘6本体)は別スコープ。

### B: rules.md ドリフト(本丸)

入力: `docs/claude/rules.md` + f(harness-rules.json)

| コード | 判定 |
|---|---|
| B-MARKER | BEGIN/END マーカーの欠落・不対応・重複 |
| B-DRIFT | マーカー間テキストが f の出力とバイト不一致(diff 添付) |

### C: settings.json ↔ L1 ルールの整合

期待集合 = permission 層ルールの deny 配列の和集合。実集合 = `.claude/settings.json` の permissions.deny。**厳密な集合一致**を要求:

| コード | 判定 |
|---|---|
| C-MISSING | 期待にあり実に無い(L1 保護が実際には効いていない — 最重要) |
| C-EXTRA | 実にあり期待に無い(harness-rules.json の外で管理される deny = 単一情報源違反。L1 追加はまず permission 層ルールとして JSON に書くのが正) |

### D: MERGE_MODE 整合

入力: `docs/claude/git-flow.md` の表の行 `| **MERGE_MODE** | <値> |` + `no-merge-on-manual` ルールの個数

| git-flow.md | ルール個数 | 判定 |
|---|---|---|
| manual | 1 | PASS |
| manual | 0 | D-MODE(manual なのに安全装置なし) |
| manual | 2+ | D-DUP(A-DUP と重複検出だが文脈を付す) |
| auto | 0 | PASS |
| auto | 1+ | D-MODE(auto なのにマージが deny される) |
| ファイル無し | 0(no-direct-push-to-base も無し) | N/A(git-flow 未採用) |
| ファイル無し | 1+(git 系ルールあり) | D-ADOPT(採用状態の不整合) |

### E: 運用ゲート(機械化可能分)

| コード | 判定 |
|---|---|
| E-LOCAL | `.claude/settings.local.json` 不在 |
| E-MEMPATH | autoMemoryDirectory が絶対パスでない / 指すディレクトリが実在しない |

機械化不能分(/hooks でのフック実在確認・ワークスペース信頼承認)は**スキル層が出力末尾に人間確認チェックリストとして必ず印字**する(§6)。「verify 緑=全部安全」という誤解を作らないため。
プラグインバージョンピンの照合はユーザーレベル設定パスに依存するため v1 では見送り(未決事項参照)。

---

## 3. レンダラ f の仕様

- 入力: パース済み harness-rules.json。出力: 節名→md テキストの写像(決定的・純関数)
- **排他3分割**: never-enforced = `deny ∧ layer∈{permission,hook}` / never-advisory = `layer:advisory`(action 不問)/ confirm-machine = `ask ∧ layer:hook`
- ルール描画(承認済み判断2・3): `**id** [層タグ]: description`、permission 層は deny 列挙、hook 層は `対象:`(tool / path / regex をインラインコード)、`理由:`(reason)、`注記:`(note、あれば)
- 並び順: JSON 配列順を保存(判断4)。空節は `(該当ルールなし)`(判断6)
- 正規化: UTF-8 / LF / 行末空白なし / 節末尾改行1
- マーカー(判断1): `<!-- BEGIN GENERATED: <節名> — source: .claude/harness-rules.json — DO NOT EDIT -->` 〜 `<!-- END GENERATED: <節名> -->`。**マーカー文字列の正準はテンプレート**(rules.md.template が空マーカー対を出荷)

## 4. check サブコマンドの失敗時挙動(エンジン哲学のミラー)

| 状況 | 挙動 |
|---|---|
| harness-rules.json 不在 | 「未導入」報告で **exit 0**(未 init プロジェクトを邪魔しない) |
| harness-rules.json パース不能 | 所見(exit 2)。壊れた JSON の報告こそ verify の仕事 |
| rules.md 不在 | 所見(B-MARKER 系) |
| git-flow.md 不在 | D を N/A スキップ(表の下2行の例外あり) |
| スクリプト内部の予期しない例外 | exit 3+スタックトレース(隠さない) |

## 5. render サブコマンド

- **前提条件**: check A が全緑であること(不正な JSON からは描画しない)。マーカー対が健全であること。どちらか欠ければ何も書かず所見報告(exit 2)
- 書込範囲: マーカー間のみ。散文(Bash 注記・モード別実効性の表など)には一切触れない
- `--dry-run`: 書込せず結果を印字
- **権限分立上の位置づけ**: render の出力は保護済み JSON のみから決まるため、実行主体に依らず「正しい md」しか書けない。よって描画・書込の機械作業は委譲可能
- **B-DRIFT 時のスキル層挙動(確定 2026-07-02: 対話確認方式)**: `render --dry-run` で diff を提示 → 会話上で人間の承諾を得る → 承諾後に `render` を実行する。無断の直接実行はしない。根拠: B-DRIFT は「render 忘れ」(上書きが正)と「マーカー内の手編集」(消える内容に救出したい情報があり得る)の縮退であり、diff を人間が見てから書く=「貼付前に読む」レビューゲートの相似形を保つ。MERGE_MODE ドリフト(検出+案内のみ)とは「**修復系操作は必ず人間の目を経る**」という抽象原則で一様(保護対象の編集=人間が実行 / 非保護生成物への決定的描画=人間が承諾)。会話上の確認のため bypassPermissions モードの影響を受けない

## 6. /harness:verify スキル層の責務

1. `harness-verify.py check` を実行し、所見を日本語で解説(ルール id → 意味の翻訳、修復手順の案内)
2. 修復は人間に案内。例外: B-DRIFT のみ §5 の対話確認方式(dry-run diff 提示 → 承諾 → render)
3. 出力末尾に**人間確認チェックリスト**を必ず印字: `/hooks` でフック実在確認 / ワークスペース信頼承認済みか
4. 未導入プロジェクトでは /harness:init を案内

## 7. template lint モード(marketplace CI 用)

- 対象: `harness-rules.json.template`。プレースホルダ `{{...}}` は許容(id の一意性判定はプレースホルダ文字列込みで実施 — `{{CONFIRM_RULE_ID}}` と `{{CONFIRM_RULE_ID}}-bash` は別 id)
- 実施: A-DUP / A-FIELD / A-ENUM / A-ORPHAN(A-REGEX はプレースホルダ含む regex をスキップ)+ `--expect-rules N` でルール数照合(CI は 10 を渡す)
- 既存 GitHub Actions に1ステップ追加。**今回の重複(PR #8 で解消)はこのモードが PR #6 時点で CI 赤にして止めていた**

## 8. 波及するファイル(実装時の変更一覧)

| ファイル | 変更 |
|---|---|
| `scripts/harness-verify.py` | 新規 |
| `tests/test_harness_verify.py` | 新規(§9) |
| `skills/verify/SKILL.md` | 新規(/harness:verify) |
| `skills/init/templates/rules.md.template` | マーカーを BEGIN/END 対に改修(`{{GENERATED_*_SECTION}}` 廃止、空マーカー対を出荷) |
| `skills/init/SKILL.md` | Phase 2: 生成節は「render 実行で生成」に変更 |
| `skills/init/templates/git-flow.md.template` | 切替手順 step 3「Claude に依頼してよい」→「`harness-verify.py render` を実行」(2箇所) |
| `.github/workflows/*.yml` | template lint ステップ追加+verify の pytest |
| `docs/MIGRATION-0.2.2-to-0.3.md` | 新規(既存 init 済みプロジェクトの移行: 旧マーカー行 → BEGIN/END 対に差し替え → `render` 初回実行 → `check` 緑確認) |
| README / 設計書 | verify 章の追補(rev.2.4 相当) |
| plugin.json + marketplace.json | **0.2.2 → 0.3.0**(両方。リリース時) |

## 9. テスト計画の骨子

- レンダラ: 決定性(再パース→バイト一致)/ 3分割の全域性・排他性 / 空節 / note・reason 有無の分岐
- 各チェック: 真陽性・真陰性のペア(A は今回の重複の実例を固定ケース化)/ D はモード×個数マトリクス全セル
- マーカー抽出: 欠落・不対応・重複・入れ子の各エッジ
- 終了コード: 0 / 2 / 3 の各経路確認+**exit-1-ゼロの二重検査**(①ソース走査で `sys.exit(1)` 不在、②異常入力の subprocess 実行が 3 を返し 1 を返さない — 1 が出たら即バグ)
- フィクスチャ: サンプル JSON 群(今回の sample-project-rules.json を種に)

## 10. 未決事項(承認待ち・持ち越し)

1. ~~終了コード~~ → **0/2/3 で確定**(§1、2026-07-02)
2. ~~スキル層の render 直接実行可否~~ → **対話確認方式(2-b)で確定**(§5、2026-07-02)
3. ~~リリース版号~~ → **v0.3(0.3.0)で確定**(2026-07-02。維持フロー契約の変更+テンプレート非互換+MIGRATION 必要、がマイナーバンプの根拠。plan/report・L3・Stop フックは v0.4 以降へ順送り)
4. プラグインバージョンピン照合(E 拡張)— ユーザーレベル設定パスの調査後に判断
5. reason を B の照合対象に含めるか → **含める**(f がバイト一致を要求する以上、自動的に含まれる。git-flow.md 再追加スニペットとの reason 微差は実装時に解消)

---

## 実装追補(Step 1〜3、2026-07-04)

実装時に確定した仕様の補完。本文と併せて正とする。

1. **所見コードの追加**: A-PARSE(harness-rules.json パース不能)/ C-PARSE(settings.json 同)/ E-PARSE(settings.local.json 同)/ T-COUNT(template lint のルール数不一致)。§4「JSON 破損=所見」に対応するコード割当
2. **argparse 使用法エラーは exit 3**: argparse 既定の exit 2 は「所見あり」と衝突するため奪還。0/2/3 の意味論を CLI 全経路で維持
3. **E の autoMemoryDirectory キー不在は所見なし**(機能未使用とみなす。破損=E-PARSE とは区別)
4. **render の書込は後方の節から**(行番号降順で差し替え): 前方差し替えによる後方マーカー行位置ズレを構造的に排除する実装詳細
5. **rules.md.template は「未生成」プレースホルダ行を出荷**: init 直後の未 render 状態は check が B-DRIFT として正しく検出する(= render 忘れの検出と同型)
6. **テンプレート↔スクリプトのマーカー同一性は pytest で機械検証**(TestTemplateMarkerSync): マーカー文字列の正準はテンプレート、スクリプトは同一文字列の再現、という §3 の関係が壊れたら CI が赤になる

検証実績: pytest 113(guard 33+verify 80)/ ミューテーション 6 変異全撃墜(適用 assert つき)/ 実データ E2E(実テンプレ lint 緑・PR #8 以前の重複再現で赤・維持ループ全周)。
