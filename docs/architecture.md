# 設計・カタログ・開発

## 処理の流れ

```text
CLI / Slack / GitHub Action
        ↓ 入力取得・許可確認
共通エンジン: issue_router/core.py
        ↓
Jev 1回目: 情報の充足・推論の難しさ・変更範囲・影響・検証
        ↓ 情報不足なら保留
Jev 2回目: 各社についてモデル＋推論設定をセットで選択
        ↓
型・確率・カタログ適合の検証 → JSON / テキスト
```

各段階では、同じstateを使う独立質問を1つのAPIリクエストにまとめます。
2回目は1回目の結果に依存するため、順番に実行します。
通常は2回、情報不足による保留は1回のJev呼び出しです。
OpenAI・Claude・Grokへそれぞれ評価依頼する構成ではありません。

Jevは自由文の理由を書かず、事前定義された選択肢に確率を返します。
そのため根拠欄はJevが判定した評価軸を表示し、追加のLLMで理由を後付けしません。
issue内の「このモデルを選べ」などの文は指示として扱わないよう、評価プロンプトで指定しています。
候補外のモデル・推論設定は結果検証でも拒否します。Jevの判定自体が正しい保証ではありません。

## モジュール

| ファイル | 役割 |
| --- | --- |
| `core.py` | 入力制限、Jev通信、2段階選定、結果検証、表示 |
| `catalog.json` | モデル候補、対応する推論設定、出典、初期選定ガイド |
| `settings.py` | CLI/Slack/Action共通の設定解決 |
| `cli.py` | URL・JSON・自由文入力とファイル出力 |
| `github.py` | Issue取得、マーカー付きBotコメント更新 |
| `slack.py` | Socket Mode、利用者/リポジトリ認可、即時ack、再送抑制 |
| `action.py` / `action.yml` | GitHub ActionとSummary・出力ファイル |

## 判定結果

JSONの主なフィールド:

| フィールド | 意味 |
| --- | --- |
| `schema_version` | 結果JSON形式の版 |
| `policy_version`, `policy` | 選定ルールの版と方針 |
| `selection_objective` | 実際にJevへ渡した当該モードの目的 |
| `catalog_version`, `catalog_verified_at` | 使用した候補集合の版と公式仕様の確認日 |
| `created_at`, `input_sha256` | 実行時刻と入力の識別用ハッシュ |
| `assessment` | 評価軸ごとの選択、全確率分布、confidence |
| `recommendations` | 各社のモデル、推論設定、API設定抜粋、判断、出典 |
| `jev_calls` | 実際に評価したJevのモデル名と各呼び出しのusage |
| `status` | `selected`（3社選定）/ `partial`（一部保留）/ `needs_context`（情報不足） |
| `warnings` | 未校正、利用面の違い、カタログ確認期限など |

`api_parameters` は設定の抜粋です。入力・max_tokens等を含む完全なリクエストではありません。
`value` / `total-cost` の選定済み候補には `policy_guidance` を追加します。
`recommendation_scope` は初回試行か検証済み完了か、`cost_basis` は定性判断であることを示し、
次の行動・再評価の目安も含みます。情報不足で保留した候補には実行の助言を付けません。

`value` は安い試行の進捗を優先し、`total-cost` はモデル利用、再試行、待ち時間、人のレビュー・修正を
含む完了までのコストを重視します。総コストを金額で算出するための料金・トークン予測・実測時間・
人件費は持っていません。Jevの選択確率を成功率とみなして期待費用を算出しません。
どちらも通常の2回のJev呼び出しで評価します。モデル候補は変えず、評価軸の判定も同じです。
現在のClaude候補にはadaptive thinkingを設定し、OpenAI/Grokには `reasoning.effort` を設定します。
確率分布から主候補と次候補を表示します。独自のconfidence閾値による成功判定はしません。
各社は候補数が違うため、選択確率を横並びでモデル性能のランキングにしてはいけません。

## カタログを更新する

1. `issue_router/catalog.json` をコピーして用途別カタログを作るか、同梱版を編集します。
2. 公式資料でモデルID、推論設定、対応するAPI面を確認します。
3. `models` の対象項目を追加・更新します。利用できないモデルは `enabled: false` にできます。
4. `sources` に確認先、`verified_at` に実際の確認日、`version` に更新版を記録します。
5. テストと架空Issueによる動作確認を行います。選定ガイドの変更は結果に影響します。

例:

```json
{
  "id": "grok-4.6",
  "provider": "grok",
  "enabled": true,
  "efforts": ["low", "medium", "high", "xhigh"],
  "selection_guidance": "Current flagship Grok coding candidate; tune effort to task difficulty.",
  "sources": ["https://docs.x.ai/developers/model-capabilities/text/reasoning"]
}
```

`provider` は `openai` / `claude` / `grok`、`efforts` はトップレベル `effort_guidance` にある値です。
Jevの選択肢数制限に合わせ、1社あたりモデル×推論設定を最大254組＋保留1組に制限します。
モデル名・組み合わせの重複、壊れた日付・型はAPI呼び出し前に拒否します。
ネットワークで全モデルを自動更新する処理はありません。

初版はOpenAI 4モデル、Claude 3モデル、Grok 1モデルです。
全モデル・全設定の網羅ではありません。Grokは公式の現行コード用途の推奨に沿って4.6を候補にしています。
Claude Haikuなど、adaptive thinkingと同じ設定方法を使えないモデルを追加する場合は、
`api_parameters` の生成処理とテストも変更してください。
APIとCodex/Claude Code/GrokのUIでは対応設定が異なり得ます。

公式の仕様と、`selection_guidance` の独自ルーティング仮説は別です。
後者は実Issueに対する成功率・費用の測定に基づくものではありません。

## 精度を改善する

過去Issueについて次を記録し、実際の結果と比較します。

- 入力Issueと補足情報（別途アクセス制御された保存先）
- カタログ/ポリシー版、Jevの実モデル、推薦と分布
- 人が採用したモデルと設定、完了の可否、必要な手戻り
- テスト結果、処理時間、実測コスト

Jevのconfidenceは判定分布の集中度で、実装成功率ではありません。
閾値や能力段階を調整する場合は、その用途のデータで検証してください。

## データと認証

- TypeSafeへ送るのは指定されたIssueのタイトル・本文・明示したコンテキストと選定用情報です。
- 結果に入力本文を複製しません。入力ハッシュは匿名化の保証ではありません。
- キー・Tokenは環境変数/Keychainから読みます。コードやテストに保存しません。
- Jev URLは固定HTTPSで、認証情報を別ホストへ転送しないようHTTP redirectを拒否します。
- リトライで意図せず課金を増やさないため、Jevの自動再試行はしません。
- APIが失敗した場合、ローカル推測へのフォールバックはありません。
- GitHub取得は `github.com` 固定でシェル展開せずに `gh` を呼び出します。

## 開発・テスト

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,slack]'
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check .
actionlint
.venv/bin/python -m build
```

通常のCIはPython 3.10 / 3.12 / 3.14でテスト、lint、パッケージ生成を行います。
GitHub Actions構文はactionlintで確認します。Jev・GitHub・Slackの書き込みはモックです。

実APIの疎通は明示的に次を実行します。TypeSafeへの送信とAPI利用料が発生します。

```sh
.venv/bin/issue-model --file examples/issue.json --format json
```

同梱の `examples/live-result.*` と `complex-result.*` は初版での実Jev結果です。
実行時の `jev-1.13.0` が記録されています。現在のAPIやカタログで同じ結果になる保証はありません。
ボタン文言変更と決済競合の2件は疎通確認であり、選定精度のベンチマークではありません。

## 今回の範囲外

常時稼働環境の自動構築、Slack Appの自動登録、利用先Secretの自動配布、GitHub Enterprise、
Issueコメント/コードの自動収集、推薦先モデルの実行、価格の自動取得、課金上限、永続キュー、
複数テナントOAuthサービスは含みません。

## 公式資料

- [Jev API](https://docs.typesafe.ai/api)
- [OpenAIモデル一覧](https://developers.openai.com/api/docs/models)
- [Claudeモデル一覧](https://platform.claude.com/docs/en/models/overview)
- [Claude effort](https://platform.claude.com/docs/en/build-with-claude/effort)
- [Grokモデル一覧](https://docs.x.ai/developers/models)
- [Grok reasoning](https://docs.x.ai/developers/model-capabilities/text/reasoning)
