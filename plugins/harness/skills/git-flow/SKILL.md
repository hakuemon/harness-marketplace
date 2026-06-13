---
name: git-flow
description: 実装が一段落したタスクを、プロジェクトの規約(ブランチ命名・コミット書式・PR テンプレ)に従ってブランチ作成→コミット→push→PR 作成(→ 条件付きマージ)まで一貫して出荷する。checklist.md のタスクが検証通過状態([?]→[x] 相当)に到達したと判断したとき自動で発動する。「実装が終わった」「コミットして」「PR を作って」「出荷して」「ship して」などの文脈、または 1 タスクの実装+検証が完了した局面で使用する。git ワークフローを自律実行する際は必ずこのスキルを参照すること。
---

# git-flow(出荷ワークフロー)

実装済みの 1 タスク分の変更を、プロジェクト規約に従って出荷する。
ship.md(touring-ai)の汎用化版。**手順は共通・不変、規約値はプロジェクト固有**で、
後者は `docs/claude/git-flow.md`(init が生成)と CLAUDE.md を参照して埋める。

## このスキルの前提と限界(必読)

- **発動の錨は checklist.md**。「1 タスクの実装+検証が完了した」を出荷の単位とする。
  checklist にタスクが無い/更新されていない状態では出荷の単位が定まらないため、
  入口ガード(下記 step 0)で停止する。
  - **前提依存**: 「作業前に checklist へ起票する」運用が守られていること。
    現状この運用はプロンプト層(operation.md)で担保され、**機械強制は未実装**。
    将来 v0.3 の Stop フック終了ゲート(checklist × git status 照合)で強制される予定。
    それまでは、この前提が崩れると本スキルは空振りする(設計上の既知の弱点)。
- **このスキルは教育層(やり方を示す)であって強制層ではない**。
  base 直 push / force push は harness-rules.json(L2)が**機械的に禁止**し、
  MERGE_MODE=manual のマージは `no-merge-on-manual` ルールが禁止する。本スキルの
  手順を守ればそもそも抵触しないが、抵触したら強制層がバックストップとして止める。
  - **base 上での直接 commit は強制層では止めない**(設計判断)。守るべき境界は
    「リモート base への push=不可逆な公開」で、これは強制層が止める。ローカル
    base 上 commit は巻き戻し容易なため、step 2(まず作業ブランチを作る)で防ぐ。
- **検証コマンドの中身は持たない**。step 5 の検証は CLAUDE.md の
  `テスト`/`ビルド`コマンド、またはプロジェクトの検証コマンドを参照して実行する。
  本スキルは「検証する・緑を確認する」というフローだけを固定する。

## 規約値の参照先

出荷前に `docs/claude/git-flow.md` を読み、以下のプロジェクト固有値を取得する
(無ければ CLAUDE.md とリポジトリ状況から推定し、推定した旨を報告する):

| 値 | 例(touring-ai) | 用途 |
|---|---|---|
| base ブランチ | `main` | PR の向き先・分岐元 |
| TYPE 語彙 | feat/fix/style/refactor/docs/chore | ブランチ名・コミット接頭辞 |
| コミット言語 | 日本語 | コミットメッセージ本文 |
| マージ方式 | squash + delete-branch | gh pr merge のオプション |
| **MERGE_MODE** | auto / manual | **step 7 の分岐**(下記) |
| PR 本文テンプレ | docs/claude/git-flow.md に記載 | gh pr create --body |
| 検証コマンド | mvnw test / tsc / lint 等 | step 5(CLAUDE.md 参照) |

## 手順

### step 0: 入口ガード(前提未達なら何もせず停止)

着手前に以下を確認し、1 つでも満たさなければ**出荷せず報告して停止する**
(誤発動・中途半端な出荷を防ぐ。ship.md step 8 の精神を入口にも置く):

1. 出荷対象のタスクが checklist.md にあり、実装が完了しているか
2. `git status` で出荷すべき変更が実在するか(変更なしなら出荷不要)
3. 変更内容が**単一タスクに収まっているか**(複数タスクが混在していたら、
   分割を提案して停止 — 1 論理変更=1 コミットの原則)

### step 1: TYPE と説明を決める

変更内容から TYPE(規約値の語彙)と `english-brief-description` を決める。

### step 2: 作業ブランチを作成

base ブランチ上にいる場合は `git switch -c TYPE/<desc>` で作業ブランチを作る。
**base ブランチへ直接コミットしない**(強制層が止めるが、手順として踏まない)。

### step 3: コミット

`git status` で対象を確認 → `git add -A` → `git commit -m "TYPE: <規約言語のメッセージ>"`。
1 論理変更=1 コミット。無関係な変更を混ぜない。

### step 4: push

`git push -u origin TYPE/<desc>`。

### step 5: 検証

CLAUDE.md / git-flow.md の検証コマンドを実行し、**全て緑であることを確認**する。
緑でない場合は **step 7 に進まず、原因と修正案を報告して停止**(ship.md step 8)。

### step 6: PR 作成

`gh pr create --base <base> --title "TYPE/<desc>" --body "<規約の PR テンプレ>"`。
PR 本文は git-flow.md のテンプレに従い、検証チェック項目を反映する。

### step 7: マージ(MERGE_MODE で分岐)

| MERGE_MODE | 挙動 |
|---|---|
| **auto**(試験稼働) | 検証が緑なら `gh pr merge <PR> <マージ方式>` でマージし、base へ戻って pull |
| **manual**(本番) | **マージしない。PR を作成したことを報告して停止**。PR が人間のレビューゲートになる。マージは人間が GitHub 上で実行する |

- **自律実行(bypassPermissions)中でも、MERGE_MODE=manual なら PR で必ず止まる**。
  これは権限分立(適用=人間のレビューゲート)を本番フェーズで保つための分岐。
- MERGE_MODE=auto は速度優先の試験稼働フェーズの設定。レビューゲートは無い。

**ドリフト検出(step 7 着手時に確認する):** MERGE_MODE は 2 箇所で 1 つの状態を表す
— git-flow.md の値と、harness-rules.json の `no-merge-on-manual` ルールの有無。
この 2 つが食い違っていたら、**マージ判断を進めず、人間に報告する**:
- git-flow.md=`auto` だが `gh pr merge` が deny される(ルール在り)→ 過剰側のドリフト
- git-flow.md=`manual` だがルールが無い → 危険側のドリフト(強制が外れている)

いずれも**自動では直さない**(ルールの編集は人間のみ=権限分立)。
git-flow.md の「ドリフトの検出と修復」節の手順を**人間に案内して停止**する。
修復手順の正準は git-flow.md(本スキルはそれを指すだけ)。

### step 8: 検証が緑でない場合

マージせず、原因と修正案を報告して停止する(どのフェーズでも共通)。

## 強制層との対応(self-documenting)

本スキルが手順で守らせる事項と、それを裏で保証する強制層の対応:

| 本スキルの手順 | 強制層(バックストップ) |
|---|---|
| base へ直接コミットしない(step 2) | 強制層では止めない(教育層に委ねる)。守る境界はリモートへの公開=下記 push |
| base へ直接 push しない(step 4 は作業ブランチへ) | harness-rules.json: `no-direct-push-to-base`(`push ... <base>` を deny) |
| force push しない | harness-rules.json: no-force-push(L2) |
| MERGE_MODE=manual で止まる(step 7) | harness-rules.json: `no-merge-on-manual`(manual 時のみ含まれ `gh pr merge` を deny。auto は本ルール無し) |

教育層(本スキル)が普段守らせ、強制層がすり抜けを止める二段構え。
強制はすべて harness-rules.json(L2)に集約され、追加のプロジェクトフックや
settings.json 改変を必要としない(エンジン無変更でルール定義のみ)。
