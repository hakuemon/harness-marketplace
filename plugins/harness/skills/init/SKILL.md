---
name: init
description: プロジェクトにハーネス一式(CLAUDE.md ポインタ構造、docs/claude/ 配下の運用ファイル、NEVER/CONFIRM ルールの定義と強制設定、チェックリスト、逸脱ログ、Auto memory 設定)を初期構築する initializer。新規プロジェクトのセットアップ、既存プロジェクトへのハーネス後付け適用、CLAUDE.md の整備・再構築の依頼で使用する。
disable-model-invocation: true
---

# Harness Initializer(v0.2.1)

プロジェクトを調査し、対話で要件を確認した上で、ハーネス一式を生成する。
生成物はすべてプロジェクトの所有物となる。ただし v0.2 以降、NEVER/CONFIRM ルールの**強制エンジン**(PreToolUse フック)はプラグイン側に常駐し、プロジェクト側の `.claude/harness-rules.json` を実行時に読む。

## 原則

1. **黙って上書きしない。** 既存ファイルへの変更は必ず差分を提示し、承認を得てから適用する。
2. **すべて記録する。** 生成・変更したファイルと、テンプレートから逸脱した判断は、理由とともに `docs/claude/deviation-log.md` に記録する。
3. **一気にやらない。** Phase 0 → 1 → 2 → 3 の順に進み、各 Phase の終わりにユーザー確認を挟む。承認なしに次の Phase へ進まない。

## Phase 0: 調査(読み取りのみ — 書き込み禁止)

以下を調査し、結果を要約して提示する。

- **技術スタックの推定:** ビルドファイル(package.json / build.gradle / pom.xml / pyproject.toml 等)、README、ディレクトリ構造から推定する
- **既存ハーネスの検出:** CLAUDE.md、.claude/(settings.json / harness-rules.json / settings.local.json)、docs/claude/ の有無と内容を確認する
- **ランタイム検証:** `python3 --version` を実行する。
  - 成功 → L2(フックエンジン)が利用可能
  - 失敗 → **警告**: L2 は動作しない。ルールは L1(permission)と advisory のみで構成する計画に切り替え、その旨を Phase 2 の生成内容と逸脱ログに反映する
- **判定の宣言:** 「新規(ハーネスなし)」「既存(部分的にあり)」のどちらかを宣言し、既存の場合は何が存在し何が欠けているかを一覧にする

## Phase 1: インタビュー

`templates/interview.md` の質問項目に従う。Phase 0 で判明済みの項目は質問せず、確認結果の追認だけを求める。

重要な確認 3 点:
- **NEVER 候補の層分類**(interview.md のフロー): 各候補を permission / hook / advisory に仕分け、ユーザーに分類結果を提示して承認を得る
- **CONFIRM の機械化選定**: ask 機械化は 2〜3 個まで。どれを機械化するかユーザーに確認する
- **Bash 書込 companion の提案**(v0.2.1): プロジェクト固有の path_glob ルールごとに「Bash 経由の書込も同じ action で拾う companion を付けるか」を確認する(interview.md の該当節参照)。**ハーネス自己保護の companion(protect-harness-files-bash)は確認不要で必ず生成する**
- **git ワークフローの採用可否と規約値**(v0.2.2): git ワークフロー(ブランチ→コミット→PR の自律出荷)を採用するか確認する。採用する場合は base ブランチ名・TYPE 語彙・コミット言語・マージ方式・**MERGE_MODE(auto/manual)**を確認する(interview.md の該当節参照)。git で管理されていないプロジェクトでは丸ごとスキップする

## Phase 2: 生成

`templates/` 配下のテンプレートを基に生成する。プレースホルダ `{{...}}` を置換する。

| 生成物 | テンプレート | 役割 |
|---|---|---|
| `CLAUDE.md` | `CLAUDE.md.template` | リーンなポインタ。詳細は docs/claude/ に委譲 |
| `.claude/harness-rules.json` | `harness-rules.json.template` | **ルール定義の正**。protect-harness-files 系の固定ルール(**-bash companion 含む 4 件**)は必ず含め、削除・改名しない |
| `.claude/settings.json` | `settings.json.template` | L1: `layer:"permission"` ルールの deny を反映(固定の自己保護 deny 6 件+プロジェクト固有分) |
| `.claude/settings.local.json` | `settings.local.json.template` | `autoMemoryDirectory` を**絶対パス**で設定(下記の注意参照) |
| `docs/claude/rules.md` | `rules.md.template` | NEVER/CONFIRM(機械化)節を harness-rules.json から**生成**して埋める。散文 CONFIRM はインタビューから記入。Bash 書込禁止の注記とモード別実効性の注記はテンプレート組み込み |
| `docs/claude/operation.md` | `operation.md.template` | 運用サイクル+Auto memory 規約+運用観察項目 |
| `docs/claude/checklist.md` | `checklist.md.template` | 状態とタスクの単一情報源 |
| `docs/claude/deviation-log.md` | `deviation-log.md.template` | 逸脱記録。初期構築の記録と python3 検証結果を記入 |
| `docs/claude/memory/` | —(空ディレクトリ+.gitkeep) | Auto memory の保存先(コミット対象) |
| `docs/claude/git-flow.md` | `git-flow.md.template` | **git ワークフロー採用時のみ**。base ブランチ・TYPE 語彙・MERGE_MODE・PR テンプレ・検証コマンドの規約値。git-flow スキルが参照する(v0.2.2) |

**companion ルールの生成規則(v0.2.1):**
- 親ルールの直後に置き、id は `<親id>-bash`、action は親を継承する
- regex は「書込動詞 + 同一パイプライン区切り内のパス断片」: `(>|\btee\b|\bsed\s+-[a-zA-Z]*i|\b(cp|mv|rm|truncate|touch|dd|ln)\b)[^|;&]*<パス断片regex>`
- パス断片はプロジェクト相対の特徴的な部分を使う(例: `docs/protected/`)。固有名ファイルは bare 名でも拾う(例: harness-rules\.json)が、`settings.json` のような一般名は必ずディレクトリ接頭辞付きにする(他用途ファイルへの誤発動防止)
- 生成した regex は**真陽性・偽陽性の双方を含む机上テスト**(python3 の re.search で 5〜10 ケース)を実行して提示し、承認を得る

**git ワークフロー(git-flow)の生成(v0.2.2・採用時のみ):**
- `docs/claude/git-flow.md` を `git-flow.md.template` から生成。プレースホルダを Phase 1 の回答で置換する: `{{BASE_BRANCH}}` / `{{TYPE_VOCABULARY}}`(表形式)/ `{{COMMIT_LANG}}` / `{{MERGE_STRATEGY}}` / `{{MERGE_MODE}}` / `{{BRANCH_EXAMPLES}}` / `{{VERIFY_CHECKLIST}}` / `{{VERIFY_COMMANDS}}`。検証コマンドは CLAUDE.md のビルド/テストコマンドと一致させる
- `.claude/harness-rules.json` に **`no-direct-push-to-base` ルールを追加**(harness-rules.json.template の該当ルールを含める)。`{{BASE_BRANCH}}` を実際の base 名に置換する
- **base push ルールの机上テスト**: 置換後の regex を python3 の re.search で真陽性・偽陽性両方を検証して提示する(例: `git push origin <base>` → deny / `git push origin feature/<base>-x` → 素通り / `git push -u origin feat/x` → 素通り)。承認を得てからルールを確定する
- **MERGE_MODE の扱い(安全側デフォルト = manual):** init は **MERGE_MODE=manual で生成する**(`no-merge-on-manual` ルールを含める=`gh pr merge` を deny)。git-flow.md の MERGE_MODE 値も `manual` にする。**auto へ移行するのは人間の明示的判断**(`no-merge-on-manual` ルールを削除し、git-flow.md の値を `auto` に変える=安全装置を外すには意図的操作が要る)。フェーズの実行時条件はエンジンでなく「ルールの有無」で表現する(エンジン無変更)
- **base 上での直接 commit は強制層では止めない**(ユーザー確認済みの設計判断)。守るべき境界は「リモート base への push=不可逆な公開」で、これは `no-direct-push-to-base` が止める。ローカル base 上 commit は巻き戻し容易なため教育層(git-flow スキル step 2)に委ねる。**git-guard.sh は生成しない**(その役割は base push ルール + no-merge-on-manual ルール + 教育層に分解吸収された)。settings.json への追加フック登録は不要
- git-flow スキル本体(プラグイン側 skills/git-flow/)は init の生成対象ではない(プラグイン同梱・全プロジェクト共通)。プロジェクト側に生成するのは規約値(git-flow.md)とルール(harness-rules.json への追加 2 件)のみ


 公式仕様で値は絶対パスまたは `~/` 始まりが必須。絶対パスはマシン固有になるため、共有される settings.json ではなく gitignore される settings.local.json に置く。プロジェクトの絶対パスは生成時に `pwd` で解決して埋め込む。**別マシンや clone 直後は settings.local.json が無いため、本スキルの再実行(または手動再生成)が必要** — この注意を deviation-log.md にも記載する。

**新規プロジェクトの場合:** 上記をそのまま生成し、生成内容の全文を提示して承認を得る。

**既存プロジェクトの場合:** いきなり生成せず、まず移行計画を提示する。
1. 既存ファイルとテンプレート構造の対応表を作る(維持 / 移動 / 分割 / 新規作成)
2. 既存 CLAUDE.md にインライン展開された詳細は docs/claude/ 配下へ移動する計画を立てる
3. **既存 rules.md がある場合(v0.1 → v0.2 移行):** NEVER/CONFIRM ルールを抽出し、層分類(interview.md のフロー)を適用して harness-rules.json への変換案を提示する。rules.md の該当節は生成式に置き換える
4. **既存 harness-rules.json がある場合(v0.2 → v0.2.1 移行):** `protect-harness-files-bash` の有無を確認し、無ければ追加差分を提示する(ルールファイルは人間編集のため、**差分の適用は人間に依頼する**)。既存 path_glob ルールへの companion 追加も提案する
5. **既存 .claude/settings.json がある場合:** 上書きせず、permissions.deny への追記と autoMemoryDirectory 追加(settings.local.json 側)の**マージ差分**を提示する
6. 計画の承認後に適用し、移動・分割・変換の判断はすべて deviation-log.md に記録する

## Phase 3: レポートと検証

1. 生成・変更したファイルの一覧と各ファイルの役割を報告する
2. ユーザーに検証手順を提示する:
   - **新しいセッションを開始する**(CLAUDE.md・フック設定はセッション開始時に読み込まれる)
   - **`/hooks` で PreToolUse に harness@meta-harness 由来のフック 2 件(編集系・Bash)が実在することを確認する**(v0.2.1: プラグインのインストール/更新直後はフックがロードされないことがある — フック不在のままテストや自律運用を始めない)
   - **ワークスペース信頼ダイアログを承認する**(settings.local.json の autoMemoryDirectory は承認後に有効。承認前に自律実行を始めない)
   - マーケットプレイス README のスモークテスト(L1 貫通・L2 deny/ask・bypass 変換・Bash companion・破損クローズ)を実施する
3. 未完了の項目(advisory に分類した昇格候補ルール、python3 不在時の L2 保留、companion を見送った path_glob ルールなど)を deviation-log.md の「残課題」節に記録する
