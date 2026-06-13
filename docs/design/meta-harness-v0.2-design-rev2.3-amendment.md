# meta-harness 設計書 rev.2.3 修正書

本書は `meta-harness-v0.2-design-rev2.md`(rev.2.1)+ `rev2.2-amendment.md` への追補差分である。
本体・rev.2.2 と並置して参照する。rev.2.2 が「v0.2 スモークテストの発見への修正」を主題とするのに対し、
本書は **v0.2.2 リリース(git-flow スキル・エンジンのテスト資産)と、設計の客観レビューで確定した一般原則(権限分立)** を主題とする。

契機: **設計の客観レビュー(2026-06-13)と、その指摘への対応(B-1 テスト資産・B-2 git-flow)、および v0.2.2 の main マージ**。
詳細な経緯は `meta-harness-checklist.md` §3-3 / §5.3 / §7、レビュー全文は `docs/reviews/design-review-2026-06-13.md` を参照。

---

## 追補1: 権限分立の明文化(「ルールファイル仕様」節の補強)

rev.2 以降「ルールファイルは人間のみ編集」と記してきたが、これは権限分立の略記である。
レビューの構造的な問い(「人間が JSON を手書きする維持フローはルール数に比例して摩耗するのではないか」)への決着として、真の不変条件を明文化する。

> ### 権限分立の明文化
>
> ルールファイルの「人間のみ編集」は権限分立の略記である。役割は三分される:
> **起草** = 隔離コンテキスト(Claude.ai。対象リポジトリへの書込手段を持たない。regex の机上テストも同所で実施できる)/
> **承認・適用** = 人間(貼付そのものがレビューゲート)/
> **被執行** = Claude Code(自分を縛る制約に対して書込不可侵 — L1 / L2 / Bash companion が機械的に保証)。
> この構造の安全性は「人間が貼付前に読む」ことに依存する(劣化経路は反射貼付。ただしルール変更は ask と違い低頻度のため、疲れの圧力は弱い見込み)。

- 維持コストはルール数に比例しない(人間は著者ではなくレビューゲート兼運搬役)。懸念は貼付と再生成の同期コストに縮退し、それは将来 `/harness:verify`(指摘2)の領域
- この分立は v0.4(/harness:update)・v0.5(サブエージェント)の権限設計でも判断基準とする。「どのコンテキストに何の権限を与えるか」を常にこの三分で問う
- rules.md.template の変更フロー行は本原則に沿って更新済み(「起草は書込手段を持たない隔離環境で行い、人間が貼付=レビューゲート」)

## 追補2: エンジンのテスト資産(「エンジン実装仕様」節の補強)

レビュー指摘1: harness-guard.py はセキュリティ判定を担うのにコミット済みテストがゼロだった。
これまで机上・実機で都度検証していたものを、versioned な回帰資産として固定した。

- 配置: `plugins/harness/tests/test_harness_guard.py`(pytest 33 ケース)+ `tests/README.md` + `.github/workflows/harness-tests.yml`(py3.10/3.12 マトリクス)
- **検証方針**: エンジンは sys.exit を多用しフックとして起動されるため、import せず**サブプロセスとして実呼び出し**し、終了経路の不変条件(exit 1 を一切踏まない/判定は stdout JSON)まで含めて検証する
- カバレッジ: 終了経路の不変条件 / L2 NEVER(force push・語順非依存)/ CONFIRM モード対応 / deny 優先(規約3)/ path 両形照合(rev.2.1)/ companion 真陽性・偽陽性・**既知偽陽性(指摘7 を現状固定)** / 失敗時 A/B/C / cwd フォールバック
- **テストの有効性をミューテーション検証で実証**: deny 優先ロジックを壊すと該当テストが、フェイルクローズを壊すと失敗時テストが赤くなることを確認(常緑のザルではない)
- 設計含意: 今後エンジンに手を入れる前提条件として、この回帰資産を緑に保つ。CI は scripts/tests の変更で自動起動する

## 追補3: git-flow スキル(新規セクション — v0.2.2 の本体)

実装完了タスクを規約に従い自律出荷(ブランチ→コミット→push→PR→条件付きマージ)するスキル。
touring-ai の実働3資産(ship.md=command / git-guard.sh=hook / CONTRIBUTING.md=doc)を、ハーネスの**教育・強制・規約の三層**に汎用化した。

### 三層分担

| 層 | 担うもの | 実体 |
|---|---|---|
| 教育 | 正しいやり方を示す | git-flow スキル(skills/git-flow/SKILL.md。プラグイン同梱・全プロジェクト共通) |
| 規約 | プロジェクト固有値 | docs/claude/git-flow.md(init が生成。base ブランチ・TYPE 語彙・MERGE_MODE・PR テンプレ・検証コマンド) |
| 強制 | 逸脱のバックストップ | harness-rules.json の L2 ルール(no-direct-push-to-base / no-merge-on-manual) |

### 起動モデル(設計判断)

- **形態は Skill(slash command でない)**。理由: 一次対象は自律実行で、人間が `/ship` を打つ機会がない。自動発動できる Skill が必須
- **発動の錨は checklist のタスク完了**(『気分』でなく客観条件)。これにより出荷=1タスク単位となりコミット粒度が安定する。誤爆・粒度肥大は入口ガード(step 0)で受ける
- **前提依存**: checklist への『作業前起票』運用が守られていること。現状この運用はプロンプト層(operation.md)のみで機械強制が無い。**強制は v0.3 Stop フック終了ゲート(checklist × git status)で後追いする設計依存**をスキル冒頭に self-documenting

### MERGE_MODE(マージ段階のモード対応)

| MERGE_MODE | 挙動 | 強制 |
|---|---|---|
| `manual`(**既定・安全側**) | PR 作成で停止。マージは人間(PR がレビューゲート) | `no-merge-on-manual` ルール在り(`gh pr merge` を deny) |
| `auto` | 検証緑ならマージまで自律 | 同ルール無し |

- **フェーズを『ルールの有無』で表現**(エンジン無変更)。v0.2.1 の Bash companion(エンジン変更なし・ルール追加のみ)と同じ三層モデルの表現力活用
- **安全側デフォルト = manual**。init は常に `no-merge-on-manual` を生成。auto 移行は人間がルールを明示的に削除(安全装置を外すには意図的操作=権限分立と整合)
- これは rev.2 の「CONFIRM のモード対応」(通常= ask / bypass = deny+停止)とは別軸のモード。permission_mode(stdin で読める実行モード)に対し、MERGE_MODE は**プロジェクトのフェーズ設定**でありルールの有無で表現する

### git-guard.sh を廃した経緯(設計が好転した記録)

当初は touring-ai 由来の git-guard.sh(base 上 commit を `git branch --show-current` で検知 / MERGE_MODE 分岐)をプロジェクトフックとして配置する計画だった。
しかし settings.json へのフック登録が L1 保護対象と絡む(レビュー指摘3=自己ブロック経路)ため難所と見ていた。壁打ちの結果、git-guard.sh の2判定を分解吸収して**スクリプト自体を不要化**した:

- **base 上 commit 禁止 → 強制層では止めない(設計判断)**。守るべき境界は「リモート base への push=不可逆な公開」のみで、それは `no-direct-push-to-base` が止める。ローカル commit は巻き戻し容易なため教育層(スキル step 2)に委ねる
- **MERGE_MODE=manual のマージ禁止 → `no-merge-on-manual` ルール**に変換(上記)

結果、**settings.json への追加フック登録ゼロ**。強制は harness-rules.json の L2 に集約され、エンジンも無変更。**指摘3(自己ブロック)と絡める必要すら消えた**。「git 状態依存の判定はエンジンの責務外」という rev.2.1 の線引きを、実装で貫いた形。

### MERGE_MODE ドリフト検出(教育層による整合監視)

git-flow.md の MERGE_MODE 値と `no-merge-on-manual` ルールの有無は「2箇所で1状態」を表す。食い違い(危険側=manual なのにルール無し/過剰側=auto なのにルール有り)を **git-flow スキルが step 7 着手時に検出し、人間に修復を案内して停止する**。

- **自動では直さない**(ルールの自動書き換えは権限分立違反=被執行が自分の制約を書く経路になる)。検出して人間に教えるに留める
- 修復手順の正準は git-flow.md(切り替え手順+再追加用ルール定義+ドリフト表を収録)。スキルはそれを指すだけ(単一情報源=指摘8)
- これは将来の `/harness:verify`(指摘2)の MERGE_MODE 整合チェックの土台。検出ロジックは既に教育層にあり、verify はそれを機械化・能動警告する

## 追補4: no-direct-push-to-base ルールの regex(例示の追加)

git-flow 採用時に init が生成する base 直 push 禁止ルールの regex(rev.2.2 修正1 の教訓「机上テストとセット」に従い検証済み):

```
git\s+push\b[^|;&]*[\s/:]{{BASE_BRANCH}}(\s|$)
```

- 真陽性: `git push origin main` / `git push -u origin main` / `git push origin HEAD:main`(refspec 右辺)/ 複数 refspec 末尾の main
- 偽陽性なし(素通り): `git push origin feature/main-menu`(base を含む別名)/ `git push -u origin feat/x`(作業ブランチ)/ `git push origin mainline`(前方一致の別名)
- 机上14ケース + 現行エンジン E2E(deny/素通り)で検証済み。`{{BASE_BRANCH}}` は init が実際の base 名に置換する

## 改訂履歴(本体の改訂履歴に追記する行)

- rev.2.3(2026-06-13): 設計の客観レビューと v0.2.2 を反映。**権限分立を不変条件として明文化**(起草/承認・適用/被執行の三分)。**エンジンのテスト資産**(pytest 33+CI、ミューテーション検証)を追加。**git-flow スキル**(教育・強制・規約の三層、Skill 形態、checklist 起点の自動発動、PR まで自律/MERGE_MODE 分岐、安全側デフォルト manual)を新規セクション化。git-guard.sh を分解吸収で廃止し settings.json 改変ゼロに着地(指摘3 と切り離し)。MERGE_MODE ドリフト検出(自動修正せず人間に案内=権限分立)。no-direct-push-to-base の regex を机上+E2E 検証つきで例示追加
