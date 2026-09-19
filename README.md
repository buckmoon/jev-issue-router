# Jev Issue Router

**Issueに適したモデルと推論設定を、JevがOpenAI・Claude・Grokそれぞれについて選びます。**
共通の評価エンジンを、ローカルCLI、Slackコマンド、GitHub Actionから利用できます。
推薦先の3社APIは実行しません。評価処理はTypeSafeのホストAPIで行います。

| 使う場所 | 操作 | 結果 |
| --- | --- | --- |
| PCローカル | `issue-model ISSUE_URL` / JSON / テキスト | ターミナル、JSONファイル |
| Slack | `/issue-model ISSUE_URL [policy]` | 実行した本人だけに返信 |
| GitHub | 手動実行、またはラベル付与 | Job Summary、任意でIssueコメント更新 |

## 導入手順

- **[ローカル](docs/local.md)** — インストール、Jev/GitHub認証、入力形式、方針設定、更新
- **[Codex共通スキル](docs/local.md#他のcodexセッションから使う)** — `$jev-issue-router` を別プロジェクトのセッションでも利用
- **[Slack](docs/slack.md)** — App登録、権限、Token、許可リスト、起動、常時運用
- **[GitHub](docs/github.md)** — 共有Action、Secret設定、手動/ラベル実行、コメント、導入例
- **[設計・カタログ・開発](docs/architecture.md)** — 判定方式、モデル更新、結果JSON、テスト、制約

## まずローカルで試す

```sh
git clone https://github.com/buckmoon/jev-issue-router.git
cd jev-issue-router
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/issue-model --file examples/issue.json
```

Python 3.10以降とJevのAPIキーが必要です。認証は `TYPESAFE_API_KEY` または既存のmacOS Keychain項目を使います。
GitHub URLの評価には `gh` の認証も必要です。詳しくは[ローカル手順](docs/local.md)を参照してください。

## GitHubリポジトリに導入

利用先のワークフローから共有Actionを呼び出します。Pythonソースのコピーは不要です。
公開後は組織内外のpublic/privateリポジトリから利用できます。
利用先の `TYPESAFE_API_KEY` Secretと、このActionを許可するActionsポリシーが必要です。

```yaml
- uses: buckmoon/jev-issue-router@main
  with:
    issue-number: '123'
    typesafe-api-key: ${{ secrets.TYPESAFE_API_KEY }}
    post-comment: 'false'
```

これはステップの抜粋です。[完全なワークフロー例](integrations/github-actions.yml)と
[導入手順](docs/github.md)を用意しています。本番ではレビューしたcommit SHAへ固定できます。

## 結果の読み方

コスパを重視する場合は2つのモードを選べます。

```sh
issue-model ISSUE_URL --policy value       # 安く試し、必要なら再評価
issue-model ISSUE_URL --policy total-cost  # 手戻り・レビュー込みの総コストを重視
```

Slackの2つ目の引数、GitHub Actionの `policy`、Codexスキルからも選べます。
初回の完遂確実性より安い試行を優先するのが `value`、最初から上位モデルを使う費用も含め
完了までの効率を判断するのが `total-cost` です。料金や節約額の実測・見積もりは行いません。
既定の `balanced` と従来の `quality` / `cost` も引き続き利用できます。

推薦するモデル・推論設定と、選択確率、confidence、次候補、選定に使った評価を表示します。
情報が足りなければ保留します。API障害時に推薦を捏造しません。

架空のIssueでJev実APIを呼び出した例:

| Issue | OpenAI | Claude | Grok |
| --- | --- | --- | --- |
| [ボタン文言変更](examples/live-result.md) | GPT-5.6 Luna / low | Sonnet 5 / low | Grok 4.6 / low |
| [決済Webhook競合](examples/complex-result.md) | GPT-6 Astra / high | Opus 5 / high | Grok 4.6 / high |

**確率は実装成功率ではありません。** この2件は動作確認であり、選定精度を証明するベンチマークではありません。
カタログの能力・コストの位置づけは初期の選定仮説です。実Issueの結果で調整してください。

## 実装・検証の範囲

- 共通エンジン、CLI、Socket Modeアダプタ、共有Actionを実装しています。
- 通常のCIはモックを使い、実API料金・Slack投稿・Issueコメントを発生させません。
- 実行時にはIssueのタイトル・本文・明示したコンテキストをJevへ送信します。
- 推薦はAPIのモデルID・設定を基準にします。各製品UIの表示名や利用権限は別途確認が必要です。
- Slack App登録と利用先リポジトリへのSecret設定は、導入先ごとに必要です。

カタログの公式確認日は2026-09-18です。モデル別の出典は[catalog.json](issue_router/catalog.json)にあります。

## ライセンス

[MIT License](LICENSE)。外部サービスの利用条件・料金、依存ライブラリのライセンスは別途適用されます。
APIキーは各利用者が用意してください。
