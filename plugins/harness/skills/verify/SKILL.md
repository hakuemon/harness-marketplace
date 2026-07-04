---
name: verify
description: ハーネス生成物の整合検証(doctor)。harness-rules.json の構造健全性、rules.md 生成節のドリフト、settings.json と L1 ルールの整合、MERGE_MODE 整合、運用ゲートを機械チェックし、所見を解説して修復を案内する。「verify」「検証して」「整合チェック」「ドリフト確認」「ハーネスの健康診断」「rules.md を再生成」などの文脈、harness-rules.json の変更後、プラグイン更新後、セッション開始時の運用確認、既存プロジェクトの移行後に使用する。
---

# verify(整合検証)

ハーネスの生成物一式が互いに整合しているかを機械判定する。判定はスクリプト(`harness-verify.py`)が行い、このスキルは**実行・解説・修復案内**を担う。

## 実行

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/harness-verify.py check --root <プロジェクトルート>
```

- 機械可読が必要なら `--json` を付ける
- 終了コード: **0**=全緑(または未導入)/ **2**=所見あり / **3**=内部エラー。**exit 1 はこのリポジトリでは「未知のクラッシュ経路」を意味するカナリア**であり、観測したらそれ自体を人間に報告する
- 未導入(harness-rules.json 不在)なら `/harness:init` を案内して終わる

## 所見の解説(コード → 意味 → 修復者)

| コード | 意味 | 修復 |
|---|---|---|
| A-DUP / A-FIELD / A-ENUM / A-MATCH / A-REGEX / A-ORPHAN / A-PARSE | harness-rules.json の構造不良(id 重複・必須欠落・不正値・空 match・regex 不能・幽霊ルール・パース不能) | **人間**(ルールファイルは人間のみ編集。修正案の提示まではしてよい) |
| B-MARKER | rules.md のマーカー対が不健全(欠落・片割れ・逆順・重複) | **人間**(MIGRATION 手順のマーカー差し替えを案内) |
| B-DRIFT | rules.md 生成節が f(harness-rules.json) と不一致 | **下記の render フロー**(唯一、このスキルが修復まで担える所見) |
| C-MISSING / C-EXTRA / C-PARSE | settings.json の deny が L1 ルールと不一致(不足=保護が効いていない/過剰=単一情報源違反)・パース不能 | **人間**(settings.json は L1 保護対象) |
| D-MODE / D-DUP / D-ADOPT | MERGE_MODE と no-merge-on-manual ルールの食い違い/git-flow 採用状態の不整合 | **人間**(git-flow.md の切替手順を案内。自動では直さない) |
| E-LOCAL / E-MEMPATH / E-PARSE | settings.local.json 不在・autoMemoryDirectory 不正・パース不能 | **人間**(内容は人間が作成する。init SKILL.md の再生成注意を案内) |

## B-DRIFT の修復フロー(このスキルの唯一の修復系操作)

**無断で render を実行しない。**必ずこの順で行う:

1. `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/harness-verify.py render --root <ルート> --dry-run` を実行し、diff を人間に提示する
2. 会話上で人間の承諾を得る(diff の内容 — 特に「マーカー内が手編集されていた」場合に消える行 — を確認してもらう)
3. 承諾後に `--dry-run` を外して実行し、直後に `check` で全緑を確認する

根拠: render の出力は保護済み JSON のみから決まるため描画・書込は委譲可能だが、**修復系操作は必ず人間の目を経る**(MERGE_MODE ドリフトの「検出+案内のみ」と同じ抽象原則。関与の深さの差は、保護対象の編集=人間が実行/非保護生成物への決定的描画=人間が承諾、に対応する)。

## 出力の締め(毎回必ず)

機械チェックの結果に関わらず、末尾に**人間確認チェックリスト**を印字する(スクリプトでは判定できない項目):

- [ ] `/hooks` で PreToolUse に harness@meta-harness 由来のフック 2 件(編集系・Bash)が実在すること
- [ ] ワークスペース信頼ダイアログを承認済みであること

「verify 緑=全部安全」ではない。この 2 点はセッション状態であり、ファイルからは判定できない。

## しないこと

- harness-rules.json / settings.json / settings.local.json / git-flow.md への書込(すべて人間の領分。B-DRIFT 以外の所見は修復案の**提示**まで)
- check 以外の文脈での render の無断実行
- 所見の握りつぶし(全所見をそのまま人間に見せる。要約で件数を減らさない)
