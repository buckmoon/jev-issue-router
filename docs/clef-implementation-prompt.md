# Clef 対応 実装開始プロンプト（Claude Opus 5.5 向け）

このファイルの「---」以下を、このリポジトリを開いた Claude Code（Opus 5.5）のセッションにそのまま貼り付けます。
PR 1 が終わってレビューしたら、「PR 2 を同じ規則で実装して」のように続けます。コミット対象ではありません。

---

# Clef 対応の実装（PR 1: エンジンと CLI）

あなたは Jev Issue Router（このリポジトリ）に Clef 対応を実装します。設計は確定済みです。
設計の再検討や代替案の提示はせず、設計どおりに実装してください。不明点は設計書の該当箇所を引用して質問し、
推測で範囲を広げないでください。

## 最初に読むもの（この順で）

1. `AGENTS.md` — リポジトリの作業規則。すべて守る
2. `docs/clef-design.md` — 設計書。特に 1、2、4、4.1、5.1〜5.5、6、7、8、10、11 章
3. `README.md`、`docs/architecture.md`、`docs/local.md`
4. `issue_router/core.py`、`settings.py`、`cli.py`、`app.py`、`action.py`、`slack.py`、
   `tests/test_router.py`、`tests/test_adapters.py`、`tests/test_app.py`、`tests/test_policies.py`、`tests/test_ios.py`

## 決定済み事項（変更しない）

- Clef は評価モデル（Issue を判定する側）として追加する。推薦対象のカタログ（`catalog.json`）には加えない。
- Jev と Clef へ送るリクエスト本文は `model` 以外を完全に同一に保つ。評価ロジック・評価軸・方針・カタログ・
  `POLICY_VERSION`・`MAX_INPUT_CHARS` は変更しない。
- `clef` と `clef-flash` の両方に対応し、評価段階（1 回目）と選定段階（2 回目）で別モデルを指定できる
  （`--clef-model` が選定段階と評価段階の既定、`--clef-assess-model` が評価段階の上書き）。既定は両段階とも `clef`。
- 2 回目の質問での `needs_context` の並び順（先頭）は現状維持。
- 結果 JSON には `evaluator: {name, host, models: {assess, select}}` を追加し、`jev_calls` の名前と `schema_version: 1` は維持する。
- Jev と Clef の自動フォールバック・自動再試行はしない。失敗はそのまま `RouterError`。
- `CLEF_URL` は loopback の http か https のみ許可。HTTP リダイレクトは拒否。エラー文に応答本文を含めない
  （Cloudflare の `errors` は数値コードだけ）。
- 認証情報は最初の API 呼び出し時に遅延して読む。起動時や `routing_options()` では Keychain を読まない。
- Workers AI の応答は `{"result": {...}, "success": true, "errors": [...]}` で包まれているので `result` を取り出してから
  既存の `validate_response` に渡す。local（Ollama 等）はエンベロープなし。
- `RouterError` は新設の `issue_router/errors.py` に移し、`core.py` から従来どおり再エクスポートする
  （`from .core import RouterError` と書いている既存コードとテストを壊さない）。

## 今回のスコープ（設計書 10 章の PR 1 だけ）

- `issue_router/errors.py`、`issue_router/evaluators.py` を新設（設計書 5.1 のスケッチを完成させる）
- `issue_router/core.py`（5.2、5.3）、`settings.py`（5.4）、`cli.py` を変更
- `app.py` / `slack.py` / `action.py` は、`route()` の引数が `jev_model` から `evaluator` に変わることへの最小限の追従だけ
  （画面の変更、Action 入力の追加、ワークフローの変更は PR 2 / PR 3 で行う）
- `tests/test_evaluators.py` を新設し、設計書 8 章の表のうち `make_evaluator`、`local_url`、`Evaluator.call`、
  `unwrap_workers_ai`、`route`、`render`、`settings` の行を実装する。既存テストはすべて緑のまま
- `docs/local.md` と `docs/architecture.md` を設計書 9 章のとおり更新する（他の文書は PR 5）
- iOS は PR 4 で対応するため `ios/` は触らない。`tests/test_ios.py` が参照する定数（`PROVIDERS`、`POLICY_VERSION`、
  `MAX_INPUT_CHARS`、`TOP_CANDIDATES`、方針名、評価軸）は変えない

## やらないこと

- 実際の Jev / Cloudflare / Ollama への接続。テストはすべてフェイクの `call` と `urllib` のモックで行う。
  合成 Issue による疎通確認は人が別途行う
- Slack / GitHub への投稿
- `git push`、PR 作成。コミットは新しいブランチ `feature/clef-evaluator` 上で行い、作者とコミッターのメールが
  GitHub noreply になっていることを `git log -1 --format='%an <%ae> / %cn <%ce>'` で確認する
- 秘密情報（キー、トークン、アカウント ID）をコード・テスト・文書・ログに書くこと。テストで使う値は明らかに偽のもの
  （例: アカウント ID `0123456789abcdef0123456789abcdef`、トークン `cf_example_not_a_real_token`）
- `.venv` を作り直すこと、`catalog.json` を変えること、`examples/` の既存ファイルを変えること

## 環境と検証コマンド

リポジトリ直下で実行します。`.venv` は Python 3.14 で、パッケージは editable インストール済みです。
`build` と `slack-bolt` は入っていないので、最初に dev と slack の extra を入れます。

```sh
.venv/bin/python -m pip install -e '.[dev,slack]'
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check .
actionlint
.venv/bin/python -m build
```

## 完了条件

- 上の 4 つの検証コマンドがすべて成功する
- `.venv/bin/issue-model --help` に `--evaluator`、`--clef-host`、`--clef-model`、`--clef-assess-model`、`--clef-url` が表示される
- `ISSUE_MODEL_EVALUATOR=clef` で `CLOUDFLARE_ACCOUNT_ID` が未設定なら、GitHub にも API にも触れる前に明確なエラーで終了する
- `route(issue, call=FakeJev())` という既存の呼び方が変更なしで動く
- 同じ Issue を Jev 設定と Clef 設定で `route()` したとき、2 つのリクエストが `model` 以外で一致することをテストで示す
- 段階分け設定（`--clef-model clef --clef-assess-model clef-flash`）で、1 回目のリクエストの `model` が `clef-flash`、
  2 回目が `clef` になり、結果の `evaluator.models` と一致することをテストで示す
- Workers AI の `success: false` 応答が、メッセージ本文を含まず数値コードだけを含む `RouterError` になることをテストで示す
- `render()` が Clef の結果で「Clef モデル推薦（暫定）」と「評価モデル: Clef (workers-ai / clef-flash → clef)」を出し、
  `evaluator` の無い旧 JSON を Jev として表示することをテストで示す

## 進め方

1. `git status --short` が空であることを確認してからブランチを切る
2. `errors.py` と `evaluators.py` → `core.py` → `settings.py` / `cli.py` → 他アダプタの最小追従 → テスト → 文書 の順に進め、
   各段階で unittest を回す
3. 変更が設計書と食い違う必要が出たら、作業を止めて該当箇所を引用して質問する
4. 終了時に次を報告する: 変更ファイル一覧、実行した検証コマンドとその結果、設計書と異なる判断をした箇所（あれば理由）、
   PR 2 以降への申し送り
