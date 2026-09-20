# GitHubリポジトリで使う

## 構成

任意の利用先リポジトリのActionsから `buckmoon/jev-issue-router` のcomposite Actionを呼びます。
実行コードはこのリポジトリから取得するため、各プロジェクトへのPythonソースのコピーは不要です。
標準の `ubuntu-latest` runnerには必要なPythonとGitHub CLIが用意されています。
Self-hosted runnerではPython 3.11以降・`gh`・Bashを用意してください（CLI単体はPython 3.10以降）。

実行するのはJevによる推薦だけです。コード変更・PR作成・推薦先モデルでの実装は行いません。

## 1. 共有Actionの利用を許可する

公開後の `buckmoon/jev-issue-router` は、組織内外のpublic/privateリポジトリから参照できます。
利用先リポジトリ/組織のActionsポリシーで、このActionの利用を許可してください。
public Actionの取得には、提供側の組織内共有設定や専用の閲覧Tokenは不要です。
対象Issueの読み取りとJev呼び出しには、次節の認証設定が必要です。

### 公開前またはprivateフォークで使う場合

提供元がprivateの間は、同じ組織のprivateリポジトリ向けに次の設定を行います。

1. 提供元リポジトリ → Settings → Actions → General
2. Accessで組織内リポジトリからのアクセスを許可
3. 利用先のActionsポリシーでこのActionを許可

この設定だけでは、別組織やpublicリポジトリからprivate Actionを利用できません。
利用先の外部コラボレーターもworkflow経由でActionのコードやログへ間接アクセスできる点に注意してください。
参考: [GitHub公式の組織内共有手順](https://docs.github.com/en/actions/how-tos/reuse-automations/share-with-your-organization)。

## 2. 利用先にSecretを設定する

利用先のSettings → Secrets and variables → ActionsでRepository Secret `TYPESAFE_API_KEY` を設定します。
組織Secretとして対象リポジトリを限定して配布することもできます。
この提供リポジトリにSecretを置くだけでは、別の利用先へ自動的に渡りません。

GitHub CLIを使う場合、次のコマンドでキーを非表示入力できます。

```sh
gh secret set TYPESAFE_API_KEY --repo OWNER/REPO
```

OpenAI・Anthropic・xAIのキーは不要です。GitHub側の認証には通常の `GITHUB_TOKEN` を使います。
Issue読み取りには `issues: read`、コメント作成/更新には `issues: write` が必要です。

## 3. 手動実行を導入する

[integrations/github-actions.yml](../integrations/github-actions.yml) を利用先の
`.github/workflows/issue-model.yml` に保存し、既定ブランチに反映します。
既定ではコメント投稿はオフです。ActionsのJob Summaryで結果を確認できます。

UI操作:

1. Actions → Recommend issue models → Run workflow
2. Issue番号、方針（balanced/quality/cost/value/total-cost/min-cost/max-quality）、コメント有無を指定
3. 完了後、実行結果ページのSummaryを確認

CLI操作:

```sh
gh workflow run issue-model.yml --repo OWNER/REPO \
  -f issue_number=123 -f policy=balanced -f post_comment=false
gh run list --repo OWNER/REPO --workflow issue-model.yml --limit 5
```

コメントを有効にする場合は `post_comment=true` にします。
このツールが作ったマーカー付きの `github-actions[bot]` コメントを探し、再実行時は更新します。
他の通常コメントや、人が同じマーカーを貼ったコメントは更新対象にしません。
初回は新規作成します。削除機能はありません。
並列実行でコメントが重複しないよう、テンプレートはリポジトリ＋Issue番号でconcurrencyを制御します。

完全に読み取り専用で運用する場合は `post-comment: 'false'` 固定にし、workflowの
`permissions.issues` を `read` に変更してください。

## 4. 任意でラベル実行を追加する

[integrations/github-label.yml](../integrations/github-label.yml) を利用先の
`.github/workflows/issue-model-label.yml` に保存して既定ブランチへ反映します。
利用先に `recommend-model` ラベルを作成します。

```sh
gh label create recommend-model --repo OWNER/REPO \
  --description 'Jevでモデルと推論設定を推薦' --color 6F42C1
```

対象Issueにラベルを付けると評価し、推薦コメントを作成/更新します。
**このテンプレートはコメント投稿を有効にしています。**
Issue本文を編集しただけでは再評価しません。再評価は手動実行か、ラベルを外して付け直してください。
提供リポジトリ自体ではラベル実行を有効にしていません。

## Actionの入力と出力

| 入力 | 既定値 | 内容 |
| --- | --- | --- |
| `issue-number` | 必須 | 正のIssue番号 |
| `typesafe-api-key` | 必須 | Jev用Secret |
| `repository` | 呼び出し元のrepo | `OWNER/REPO` |
| `github-token` | `github.token` | 対象Issueを読めるToken |
| `policy` | `balanced` | `balanced` / `quality` / `cost` / `value` / `total-cost` / `min-cost` / `max-quality` |
| `jev-model` | `jev-latest` | 評価に使うJevモデル |
| `catalog` | 同梱カタログ | runner上のカタログ絶対パス |
| `post-comment` | `false` | `true` の場合だけコメント作成/更新 |

`value` は安い初回試行、`total-cost` は手戻りやレビュー時間も含む完了までのコストを重視します。
両者とも金額の見積もりではなく、定性的なモデル選定です。

他リポジトリのIssueを `repository` で指定する場合、通常の `GITHUB_TOKEN` は範囲外です。
別のGitHub App installation token等、対象を閲覧できるTokenを `github-token` へ渡してください。
コメント更新は標準の `github-actions[bot]` を対象にしています。独自App/PATの場合は
`post-comment: 'false'` で使い、必要なら出力レポートを自身の投稿処理へ渡してください。

| 出力 | 内容 |
| --- | --- |
| `status` | `selected` / `partial` / `needs_context` |
| `result-path` | 確率分布、評価、モデル設定を含むJSONのrunner上の絶対パス |
| `report-path` | Markdownレポートのrunner上の絶対パス |

例:

```yaml
- uses: buckmoon/jev-issue-router@main
  id: recommend
  with:
    issue-number: ${{ inputs.issue_number }}
    typesafe-api-key: ${{ secrets.TYPESAFE_API_KEY }}
- name: Read recommendation status
  env:
    STATUS: ${{ steps.recommend.outputs.status }}
  run: echo "$STATUS"
```

JSON/Markdownはrunnerの一時ディレクトリへ保存されます。artifactとして自動アップロードはしません。
永続保存が必要なら、利用先の保存方針に従って `result-path` / `report-path` をartifactへ渡してください。

## カスタムカタログを利用する

利用先のカタログをcheckoutしたうえで、絶対パスを渡します。

```yaml
- uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6
  with:
    persist-credentials: false
- uses: buckmoon/jev-issue-router@main
  with:
    issue-number: ${{ inputs.issue_number }}
    typesafe-api-key: ${{ secrets.TYPESAFE_API_KEY }}
    catalog: ${{ github.workspace }}/.github/model-catalog.json
```

カタログと実行コードは信頼するブランチから取得してください。
`pull_request_target` で未信頼のPRコードをcheckoutして実行する構成は用意していません。

## 版の固定と更新

テンプレートの `@main` は導入しやすい参照です。更新を管理したい場合は
提供リポジトリのレビュー済みcommit SHA（40文字）へ置き換えてください。
Actionのコード・同梱カタログは同じcommitに固定されます。
Jev自体のモデルを固定するには `jev-model` も指定します。

提供リポジトリの `.github/workflows/recommend.yml` は、自身のIssueに対する手動確認用です。
自動CIとは別で、Secretと対象Issueが用意されている場合にだけ実行します。

## トラブル対応

| 症状 | 確認すること |
| --- | --- |
| Action not found / repository not found | 提供元の公開状態、Actionsポリシー、参照SHA。privateの場合は組織内共有設定も確認 |
| TYPESAFE_API_KEYがない | Secretは呼び出し元repo/組織側に設定されているか |
| Resource not accessible by integration | `issues` 権限、組織の上限、別repo用Tokenの有無 |
| Invalid issue number | 正の整数だけを指定しているか |
| 成功だが推薦保留 | `status` を確認しIssueの情報を追加 |
| 推薦済みだがコメントなし | 既定はSummaryのみ。`post-comment` がtrueか |
| コメントで失敗した | Summary/一時ファイルは先に作成されますが、job自体は失敗を返します |

実Issueを使う推薦workflowとSlack連携は、通常のCI成功とは別の動作確認です。
