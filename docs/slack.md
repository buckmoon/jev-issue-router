# Slackで使う

## 構成

Slack Appを各ワークスペースに作成し、PCまたは常時稼働サーバーからSocket Modeで接続します。
公開HTTPサーバー、受信用URL、受信ポートは不要です。SlackとGitHubと評価モデル（TypeSafe、またはCloudflare Workers AI）への外向き通信が必要です。
Clefを手元のサーバーで動かす場合、評価モデルへの外向き通信は不要です。
1プロセス・1ワークスペースの構成です。複数ワークスペースはAppとプロセスを分けます。
OAuthで不特定多数のワークスペースへ配布するSaaS構成は含みません。

## 1. ローカル環境を準備する

先に[ローカル手順](local.md)で評価モデル（Jev / Clef）とGitHubの認証を確認します。

```sh
cd ~/dev/Github/jev-issue-router
.venv/bin/python -m pip install -e '.[slack]'
.venv/bin/issue-model-slack --help
```

## 2. Slack Appを作成する

1. [Your Apps](https://api.slack.com/apps)から「Create New App」→「From a manifest」を選びます。
2. 利用するワークスペースを選びます。承認が必要なワークスペースでは管理者へ申請します。
3. JSON形式で [slack-manifest.json](../integrations/slack-manifest.json) の内容を貼り付けて作成します。
4. Socket Modeが有効になっていることを確認します。
5. Basic Information → App-Level TokensでTokenを生成し、`connections:write` を付けます。
   取得する `xapp-...` が `SLACK_APP_TOKEN` です。
6. OAuth & Permissionsからワークスペースへインストールします。
   Bot User OAuth Tokenの `xoxb-...` が `SLACK_BOT_TOKEN` です。

Bot側のOAuth scopeは `commands` だけです。チャンネル履歴やDMは読みません。
返信にはSlash Commandのresponse URLを使うため、通常のチャンネル投稿権限は要求しません。
Socket ModeではSlash Commandの公開Request URLを設定する必要はありません。

## 3. 許可する利用者とリポジトリを決める

Slackプロフィールのメニューから「メンバーIDをコピー」で `U...` のIDを取得します。
利用を許可する人と、読ませてよいGitHubリポジトリをカンマ区切りで指定します。

```sh
export SLACK_ALLOWED_USERS='U0123456789,U9876543210'
export GITHUB_ALLOWED_REPOS='buckmoon/project-a,buckmoon/project-b'
```

ワイルドカードは使えません。空の場合は起動しません。
GitHubの情報取得には、このプロセスの `GH_TOKEN` または `gh auth` の認証を使います。
Slack利用者本人のGitHub権限を自動照合する方式ではありません。
**許可した利用者は、許可リポジトリすべてに対して評価を実行できます。**
権限の異なるチームは別のApp・プロセス・許可リストに分けてください。

プロセスは起動時にBot tokenの所属ワークスペースを確認し、別ワークスペースのリクエストを拒否します。

## 4. Tokenを設定して起動する

zshで非表示入力する例です。

```zsh
read -rs 'SLACK_APP_TOKEN?Slack app token: '
export SLACK_APP_TOKEN
echo
read -rs 'SLACK_BOT_TOKEN?Slack bot token: '
export SLACK_BOT_TOKEN
echo
```

続けて同じターミナルで起動します。評価モデルの認証（Jev / Clef）はローカルCLIと共通です。

```sh
cd ~/dev/Github/jev-issue-router
.venv/bin/issue-model-slack
```

既定の推薦方針やカタログを変える例:

```sh
.venv/bin/issue-model-slack --policy quality --catalog /absolute/path/catalog.json
```

### 評価モデルにClefを使う

評価モデルはプロセスの起動時に決まり、全員のコマンドに適用されます。Slackのコマンド引数では切り替えられません
（利用者が課金先を変えられないようにするため）。切り替えるにはプロセスを再起動します。

```sh
# Cloudflare Workers AI（CLOUDFLARE_API_TOKEN は上と同じ方法で非表示入力してexport）
export CLOUDFLARE_ACCOUNT_ID=<32桁の16進数のアカウントID>
.venv/bin/issue-model-slack --evaluator clef
# 応答待ちを短くする段階分け（評価段階 clef-flash → 選定段階 clef）
.venv/bin/issue-model-slack --evaluator clef --clef-assess-model clef-flash
# このPC内のOllama等（外部送信なし）
.venv/bin/issue-model-slack --evaluator clef --clef-host local --clef-model clef-flash
```

アカウントIDやモデル名が正しくない場合は起動時にエラーで止まります。トークンは最初の評価時に読みます。
Slackの対話利用では応答待ちが体験に直結するため、段階分けか高速（`--clef-model clef-flash`）が向いています
（校正前の仮説です。[使い分け](local.md#clef-と-clef-flash-の使い分け)）。
Clefの結果には「未校正」の警告が付き、最後の行に「評価モデル: Clef (...)」が表示されます。

## 5. Slackから実行する

```text
/issue-model https://github.com/buckmoon/project-a/issues/123
/issue-model https://github.com/buckmoon/project-a/issues/123 quality
/issue-model https://github.com/buckmoon/project-a/issues/123 cost
/issue-model https://github.com/buckmoon/project-a/issues/123 value
/issue-model https://github.com/buckmoon/project-a/issues/123 total-cost
```

2つ目の引数は `balanced` / `quality` / `cost` / `value` / `total-cost` / `min-cost` / `max-quality` です。省略すると起動時の既定値になります。
`value` は安い初回試行、`total-cost` は再試行・レビュー・手戻り込みの完了までのコストを優先します。
コストは定性的な判断で、自動的なモデル切替は行いません。
返信は呼び出した本人だけに表示されるephemeralメッセージです。
OpenAI・Claude・Grokの推薦、推論設定、選択確率、次候補、評価軸が表示されます。
結果をチャンネル全体へ共有する機能は初版に含みません。

Issueのタイトル・本文は起動時に選んだ評価モデル（TypeSafe、Cloudflare Workers AI、または指定したClefサーバー）へ送信されます。
Slack履歴は送信しません。
利用者/リポジトリの許可確認を済ませてからIssueを取得します。

## 運用

- PCがスリープ・オフライン・プロセス停止中は応答できません。停止は `Ctrl+C` です。
- 同時評価は1件です。実行中の追加要求には再実行を案内します。
- 同じSlack `trigger_id` の再送は5分間、最大256件のメモリ内履歴で抑制します。
  プロセス再起動をまたぐ重複抑制や永続キューはありません。
- 日次課金上限は実装していません。利用者許可リストと、TypeSafe・Cloudflare側の利用管理を併用します。
- 更新後はプロセスを再起動してください。稼働中のカタログは起動時に読み込んだ内容です。
- 常時運用する場合は同じコマンドをsystemd等で管理し、TokenはサービスのSecret管理から渡します。
  macOS Keychainはログインセッション依存なので、ヘッドレスサーバーでは `TYPESAFE_API_KEY` / `CLOUDFLARE_API_TOKEN` を使います。

## トラブル対応

| 症状 | 確認すること |
| --- | --- |
| `/issue-model` が見つからない | Appのインストール先、manifestのSlash Command、再インストール |
| `dispatch_failed` / タイムアウト | PC起動、Socket Mode接続、App tokenの `connections:write`、ネットワーク |
| 利用が許可されていない | `SLACK_ALLOWED_USERS` のメンバーID、Botの所属ワークスペース |
| Repository is not allowed | `GITHUB_ALLOWED_REPOS` の完全な `OWNER/REPO` |
| GitHub request failed | Bot実行環境の `gh auth status` / `GH_TOKEN` とrepo閲覧権限 |
| 起動時に `Set CLOUDFLARE_ACCOUNT_ID` | `--evaluator clef` で `CLOUDFLARE_ACCOUNT_ID` が未設定か形式違い |
| Clef HTTP 401/403、Clef network error | [ローカル手順のよくある問題](local.md#よくある問題)と同じ確認 |
| 起動時のinvalid_auth等 | app tokenとbot tokenの取り違え、無効化・再生成の有無 |

実ワークスペースへのApp作成・Token発行・コマンド応答確認は導入先ごとに必要です。
通常のテストはSlackへ接続せず、認可・即時ack・重複抑制・返信の振る舞いを検証します。

公式資料: [Socket Mode](https://docs.slack.dev/tools/bolt-python/concepts/socket-mode/)、
[Slash Command](https://docs.slack.dev/tools/bolt-python/concepts/commands/)。
