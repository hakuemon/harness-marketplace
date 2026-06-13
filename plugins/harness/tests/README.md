# harness-guard.py テスト資産

設計レビュー(2026-06-13、指摘1)への対応。harness-guard.py はセキュリティ判定を
担うのにコミット済みテストがゼロだった。本ディレクトリは、これまでセッション内で
都度行っていた机上テスト/実機テストを **versioned な回帰資産**として固定する。

## 実行

```bash
cd plugins/harness
python3 -m pytest tests/ -v
```

依存は pytest のみ(エンジン本体は標準ライブラリのみ・pip 依存ゼロを維持)。

## 検証方針

エンジンは `sys.exit` を多用しフックとして起動されるため、import せず
**サブプロセスとして実呼び出し**する。`CLAUDE_PROJECT_DIR` と stdin を制御して
PreToolUse フックの実呼び出しを再現し、**終了経路の不変条件(exit 1 を一切踏まない /
判定は stdout JSON)** まで含めて検証する。

## カバレッジ(33 ケース)

| 区分 | 検証内容 | 対応する設計判断 |
|---|---|---|
| 終了経路の不変条件 | deny も素通りも exit 0(判定は stdout) | rev.2 実装規約1 / checklist §7「exit 1 経路ゼロ」 |
| L2 NEVER | force push の deny・語順非依存・id が理由に乗る | スモークテスト #2 / rev.2.2 修正1(語順穴) |
| L2 CONFIRM モード対応 | 通常= ask / bypass = deny+停止 / キー名の揺れ | rev.2 CONFIRM のモード対応 |
| deny 優先(規約3) | JSON 上 ask が先でも deny が勝つ | rev.2.1「deny は ask に優先」 |
| path 両形照合 | 相対パス入力でも絶対 glob にマッチ | rev.2.1「path は絶対・相対両形」 |
| companion 真陽性 | `>>`・`sed -i`・`tee`・`cp/mv/rm` 等で保護パス書込を deny | v0.2.1 / rev.2.2 修正2 |
| companion 偽陽性 | `cat`・`grep`・`git checkout`・保護→他所書出は素通り | v0.2.1 companion regex の設計 |
| companion 既知偽陽性 | `grep '>' 保護ファイル` の deny を**現状固定** | レビュー指摘7(安全側の既知挙動) |
| 失敗時挙動 A/B/C | 不在=オープン / 破損・スキーマ不適合=クローズ / stdin 破損の両分岐 | rev.2 失敗時マトリクス |
| cwd フォールバック | env 不在時に event.cwd から解決 | rev.2.1 動作フロー4 |

## 既知の偽陽性テストの扱い

`TestCompanionKnownFalsePositive` は「直すべきバグ」ではなく**現状の振る舞いの記録**。
`grep '>' 保護ファイル` のような読み出しが安全側に倒れて deny される挙動を固定している。
将来 regex を改良してこの偽陽性を消した場合、このテストが落ちることで変更に気づける。
その時はテストを更新し、deviation-log に記録すること。

## テストの有効性(セルフチェック)

作成時にミューテーション検証を実施済み。エンジンの deny 優先ロジックを壊すと
`TestDenyWinsOverAsk` が、フェイルクローズを壊すと `TestFailureModes` が
それぞれ赤くなることを確認した(テストが回帰を捕まえる「歯」を持つ証拠)。
