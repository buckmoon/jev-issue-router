# 設計・カタログ・開発

## 処理の流れ

```text
CLI / macOSアプリ / iOSアプリ / Slack / GitHub Action
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
| `repo.py` | ローカルGitリポジトリのメタデータ収集（ファイル内容は読まない、件数上限つき） |
| `app.py` | macOSアプリ: 専用ウィンドウに表示するローカル画面（127.0.0.1限定）、Keychainへのキー保存、`.app` 生成 |
| `github.py` | Issue取得、マーカー付きBotコメント更新 |
| `slack.py` | Socket Mode、利用者/リポジトリ認可、即時ack、再送抑制 |
| `action.py` / `action.yml` | GitHub ActionとSummary・出力ファイル |
| `ios/` | iOSアプリ。下記のとおりエンジンのSwift移植を含みます |

### iOSアプリ（Swift移植）

iOSではPythonが動かないため、`ios/JevIssueRouter/Engine/` が `core.py` / `policies.py` の移植になっています。
唯一の意図的な重複です。`catalog.json` はビルド時に同梱する写しを `ios/sync-catalog.sh` で更新します。
リポジトリのメタデータ収集（`repo.py`）はiOS版にはありません。

評価軸・方針・カタログ・結果JSONを変更したらSwift側も更新してください。
`tests/test_ios.py` が、定数・方針名・評価軸の選択肢・カタログの写しのずれを検出します。
移植の同値性は、同じJev応答をPython版とSwift版に与えて結果JSON・送信リクエスト・表示テキストを
突き合わせて確認します（`input_sha256` を含む。表示テキストは `--policy` の言い換え1行のみ差があります）。

## 判定結果

JSONの主なフィールド:

| フィールド | 意味 |
| --- | --- |
| `schema_version` | 結果JSON形式の版 |
| `policy_version`, `policy` | 選定ルールの版と方針 |
| `selection_objective` | 実際にJevへ渡した当該モードの目的 |
| `catalog_version`, `catalog_verified_at` | 使用した候補集合の版と公式仕様の確認日 |
| `created_at`, `input_sha256` | 実行時刻と入力の識別用ハッシュ（リポジトリ指定時はそのメタデータも含む） |
| `recommendations.*.top_candidates` | その会社が選定保留のときだけ。確率の高い順に最大5件の `model` / `effort` / `probability`。推薦ではなく内訳で、`model` / `effort` / `api_parameters` は付けない |
| `missing_context` | Jevが不足と判断した情報の種類（`goal` / `current_state` / `target` / `completion`）。1回目の評価と同じ呼び出しで判定。保留するのは `goal` が不足のとき（または不足項目の特定なしに情報不足と判定されたとき）だけ。それ以外の不足は暫定選定に進み、2回目の評価にも渡す |
| `repository` | リポジトリ指定時のみ。Jevへ送信したメタデータそのもの |
| `assessment` | 評価軸ごとの選択、全確率分布、confidence |
| `recommendations` | 各社のモデル、推論設定、API設定抜粋、判断、出典 |
| `jev_calls` | 実際に評価したJevのモデル名と各呼び出しのusage |
| `status` | `selected`（3社選定）/ `partial`（一部保留）/ `needs_context`（情報不足） |
| `warnings` | 未校正、利用面の違い、カタログ確認期限など |

`api_parameters` は設定の抜粋です。入力・max_tokens等を含む完全なリクエストではありません。
`value` / `total-cost` / `min-cost` / `max-quality` の選定済み候補には `policy_guidance` を追加します。
`min-cost` / `max-quality` では各候補の説明にカタログ内の順位を付け、`max-quality` では候補を各社の最上位モデルに限定します。
そのためカタログは、各社のモデルを安い順（最後が最も高性能）に並べてください。
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
有効なモデルをネットワーク経由で自動更新する処理はありません。新しいモデルの検出は次の節の方法で行います。

## 新しいモデルを検出する

各社の公式モデル一覧API（OpenAI・Anthropic・xAIの `GET /v1/models`）とカタログを比較します。
一覧の取得は無料ですが、各社のAPIキーが必要です。キーは環境変数で渡し、未設定の会社は確認を飛ばします。

```sh
OPENAI_API_KEY=... ANTHROPIC_API_KEY=... XAI_API_KEY=... issue-model-catalog          # 確認のみ
OPENAI_API_KEY=... ANTHROPIC_API_KEY=... XAI_API_KEY=... issue-model-catalog --write  # カタログへ追加
```

実際にはシェル履歴に残らないよう、[ローカル手順](local.md#jev認証)と同じ非表示入力で環境変数を設定してください。

- **提案の対象**: `issue_router/model_watch.json` の `include` に合い、`exclude`（音声・画像・埋め込みなど）に当たらないIDです。
  日付付きスナップショットは除きます。一覧上の作成日がカタログの `verified_at` より前のモデルも、確認済みとして除外します。
- **追加の方法**: `--write` は新しいモデルを **`enabled: false`** で追加します。iOS用カタログにも同じ内容を書き込みます。
  - `efforts` は、同じ会社の既存モデルからの仮のコピーです。
  - `selection_guidance` は `UNREVIEWED:` で始まる仮の文です。
  - Jevはこれらのモデルを選びません。仮の文のまま `enabled: true` にすると、カタログの検証でエラーになります。
- **有効化する前に**: 公式資料で推論設定と位置づけを確認し、各社のモデルを安い順に並べ直してから有効化します。
  `sources` と `verified_at` も更新します。不要なモデルは削除し、`ignored` に追加すると再提案されません。
- **一覧から消えたモデル**: 報告だけで、自動では無効化しません。廃止・アカウントの権限・一時的な欠落を区別できないためです。

### GitHub Actionで定期確認する

`.github/workflows/model-watch.yml` が1日4回（UTC 0:23 / 6:23 / 12:23 / 18:23）確認します。手動実行もできます。

1. リポジトリのActions Secretに `OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、`XAI_API_KEY` を登録します。
   一覧の読み取りだけに使います。未登録の会社は確認を飛ばし、すべて未登録なら失敗します。
2. 新しいモデルが見つかると、`automation/model-catalog` ブランチにコミットし、PRを作成します。mainへ直接pushはしません。
3. PRが開いている間は、次の確認を行いません。レビュー中の編集が上書きされないようにするためです。
   マージかクローズの後、次の定期実行で残りの差分を提案します。
4. `GITHUB_TOKEN` で作成したPRでは、GitHubの仕様によりCIが自動実行されません。
   ワークフローがPR作成前に全テストを実行しますが、レビュー時にはブランチへpushするか、CIを手動で実行してください。

結果は毎回Job Summaryに出ます。新規のモデルと、一覧に無い有効モデルが一覧で分かります。

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
