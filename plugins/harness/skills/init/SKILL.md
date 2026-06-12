---
name: init
description: プロジェクトにハーネス一式(CLAUDE.md ポインタ構造、docs/claude/ 配下の運用ファイル、NEVER/CONFIRM ルール、チェックリスト、逸脱ログ)を初期構築する initializer。新規プロジェクトのセットアップ、既存プロジェクトへのハーネス後付け適用、CLAUDE.md の整備・再構築の依頼で使用する。
disable-model-invocation: true
---

# Harness Initializer

プロジェクトを調査し、対話で要件を確認した上で、ハーネス一式を生成する。
生成物はすべてプロジェクトの所有物となる(生成後、このプラグインへの依存は残らない)。

## 原則

1. **黙って上書きしない。** 既存ファイルへの変更は必ず差分を提示し、承認を得てから適用する。
2. **すべて記録する。** 生成・変更したファイルと、テンプレートから逸脱した判断は、理由とともに `docs/claude/deviation-log.md` に記録する。
3. **一気にやらない。** Phase 0 → 1 → 2 → 3 の順に進み、各 Phase の終わりにユーザー確認を挟む。承認なしに次の Phase へ進まない。

## Phase 0: 調査(読み取りのみ — 書き込み禁止)

以下を調査し、結果を要約して提示する。

- **技術スタックの推定:** ビルドファイル(package.json / build.gradle / pom.xml / pyproject.toml 等)、README、ディレクトリ構造から推定する
- **既存ハーネスの検出:** CLAUDE.md、.claude/、docs/claude/ の有無と内容を確認する
- **判定の宣言:** 「新規(ハーネスなし)」「既存(部分的にあり)」のどちらかを宣言し、既存の場合は何が存在し何が欠けているかを一覧にする

## Phase 1: インタビュー

`templates/interview.md` の質問項目に従う。ただし Phase 0 で判明済みの項目は質問せず、確認結果の追認だけを求める。ユーザーの負担を最小にすること。

主要項目: プロジェクト名 / 技術スタック / フェーズ成熟度(1〜4)/ NEVER ルール候補 / CONFIRM ルール候補 / ビルド・テスト・起動コマンド

## Phase 2: 生成

`templates/` 配下のテンプレートを基に生成する。プレースホルダ `{{...}}` をインタビュー結果で置換する。

| 生成物 | テンプレート | 役割 |
|---|---|---|
| `CLAUDE.md` | `CLAUDE.md.template` | リーンなポインタ。詳細は docs/claude/ に委譲 |
| `docs/claude/rules.md` | `rules.md.template` | NEVER / CONFIRM ルール定義 |
| `docs/claude/operation.md` | `operation.md.template` | 運用サイクルとセッション開始・終了手順 |
| `docs/claude/checklist.md` | `checklist.md.template` | 状態とタスクの単一情報源 |
| `docs/claude/deviation-log.md` | `deviation-log.md.template` | テンプレートからの逸脱記録 |

**新規プロジェクトの場合:** 上記をそのまま生成し、生成内容の全文を提示して承認を得る。

**既存プロジェクトの場合:** いきなり生成せず、まず移行計画を提示する。
1. 既存ファイルとテンプレート構造の対応表を作る(維持 / 移動 / 分割 / 新規作成)
2. 既存 CLAUDE.md にインライン展開された詳細は docs/claude/ 配下へ移動する計画を立てる
3. 計画の承認後に適用し、移動・分割の判断はすべて deviation-log.md に記録する

## Phase 3: レポートと検証

1. 生成・変更したファイルの一覧と各ファイルの役割を報告する
2. ユーザーに検証手順を提示する: **新しいセッションを開始し**、簡単なタスクを依頼して、CLAUDE.md とルールが参照されることを確認する(ハーネスはセッション開始時に読み込まれるため、現在のセッションでは検証できない)
3. 未完了の項目(Hook 化候補の NEVER ルールなど)を deviation-log.md の「残課題」節に記録する
