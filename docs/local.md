# ローカルで使う

## 必要なもの

- Python 3.10以降（macOS / Linux。WindowsではPython CLI自体は利用可能ですが未検証）
- TypeSafe/JevのAPIキー
- GitHub Issue URLを読む場合のみ、GitHub CLI `gh` と対象Issueの閲覧権限

OpenAI・Anthropic・xAIのAPIキーは不要です。推薦するモデルは実行しません。

## インストール

初めて取得するPCでは次を実行します。既にclone済みならそのフォルダへ移動してください。

```sh
mkdir -p ~/dev/Github
cd ~/dev/Github
git clone https://github.com/buckmoon/jev-issue-router.git
cd jev-issue-router
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/issue-model --help
```

公開後はcloneにGitHub認証は不要です。Issue URLの評価には別途ghの認証が必要です。
任意の場所からコマンドを使いたい場合は、現在のシェルにPATHを設定します。
毎回使う場合は同じ行を自身のシェル設定に追加できます。

```sh
export PATH="$HOME/dev/Github/jev-issue-router/.venv/bin:$PATH"
issue-model --help
```

ソースを編集しない利用者は `pip install .` でも使えます。PyPIには公開していません。

## Jev認証

認証の優先順位は次のとおりです。

1. `TYPESAFE_API_KEY` 環境変数
2. macOS Keychainのサービス `local.jev.typesafe`、アカウント名がログインユーザーの項目

既存のJevBridgeでKeychain登録済みなら、そのまま利用できます。
別のPCでは環境変数を使うか、macOSの「キーチェーンアクセス」で上記サービス名・アカウント名の
汎用パスワード項目として登録してください。キー値をソース、シェル履歴、チャットへ貼り付けないでください。

環境変数へ非表示で入力する例（macOS標準のzsh）:

```zsh
read -rs 'TYPESAFE_API_KEY?TypeSafe API key: '
export TYPESAFE_API_KEY
echo
```

Bashの場合:

```bash
read -r -s -p 'TypeSafe API key: ' TYPESAFE_API_KEY
export TYPESAFE_API_KEY
printf '\n'
```

これらの環境変数は、そのターミナルから起動するプロセスにだけ引き継がれます。
環境変数ファイルの自動読み込みはしません。キー未設定・Keychain拒否時はエラー終了します。

## 入力方法

### GitHub Issue URL

```sh
gh auth login --hostname github.com
gh auth status --hostname github.com
issue-model https://github.com/OWNER/REPO/issues/123
```

`--issue URL` も同じ動作です。取得するのはタイトルと本文です。
コメント・添付・リンク先・コードの自動取得はありません。
GitHub EnterpriseホストやPull Requestは未対応です。

### JSONファイル

```json
{
  "title": "保存ボタンの文言変更",
  "body": "保存を変更を保存へ変更する。動作変更なし。既存の画面テストを更新する。",
  "context": "対象は設定画面の1コンポーネント。完了条件は新文言の表示と既存テストの成功。"
}
```

```sh
issue-model --file examples/issue.json
cat examples/issue.json | issue-model --file -
```

### 自由文・標準入力

```sh
issue-model --text '設定画面の保存ボタンを「変更を保存」に変更し、画面テストを更新する。'
cat task.md | issue-model --text -
```

入力はURL、`--issue`、`--file`、`--text` のうち1つだけ指定します。
タイトル・本文・コンテキストの合計60,000文字を超える場合は、要約して再実行します。

### 追加コンテキスト

```sh
issue-model https://github.com/OWNER/REPO/issues/123 --context context.md
```

指定したファイルもJevへ送信されます。これはJSONの `context` を置き換えます。
関連する仕様・対象コンポーネント・完了条件など、選定に必要な内容だけを入れてください。

## 推薦方針と出力

```sh
issue-model --file examples/issue.json --policy balanced
issue-model --file examples/issue.json --policy quality
issue-model --file examples/issue.json --policy cost
issue-model --file examples/issue.json --policy value
issue-model --file examples/issue.json --policy total-cost
issue-model --file examples/issue.json --format json --output result.json
```

| 設定 | 意図 |
| --- | --- |
| balanced | 十分な能力を持つ候補の中でコストとのバランスを取る。既定値 |
| quality | 本質的な難しさ・不確実性に対して能力を優先する |
| cost | 十分と判断できる範囲で低コストの候補を優先する |
| value | まず安いモデル・設定で小さく試す。初回での完遂より得られる進捗を重視し、手戻りや後の切替を許容する |
| total-cost | 再試行・レビュー・手戻り時間まで含め、検証済みの完了までの総コストを優先する |

料金額の見積もりは行いません。カタログの定性的な説明に基づく選定です。
`value` と `total-cost` は別の目的です。前者は安い初回試行、後者は最後までの総コストを重視します。
たとえば調査を小さく試せるIssueでは `value`、失敗後の原因調査やレビューに時間がかかるIssueでは
`total-cost` を使えます。後者では最初から上位モデルを使う方が得だと判断することもあります。
どちらも最安モデルや低い推論設定を強制せず、Jevがモデルと設定を一緒に選びます。
同じIssueで両モードが同じ候補を選ぶこともあります。

結果には試行・再評価の目安を含めます。`value` で進捗が出ない、失敗を繰り返すなどの場合は、
得られた情報を `--context` で追加し、`--policy total-cost` で再評価できます。
モデルの実行・自動切替はしません。料金、所要時間、手戻りの実測はなく、金額ベースの期待値計算ではありません。
既知の作業時間制約や失敗時の負担を `context` に含めると、総コスト判断の材料にできます。

`--output` は既存ファイルを上書きします。通常は標準出力だけで、評価の履歴保存はしません。
`--format slack` はSlackにも貼れるテキストを返します。投稿は行いません。

終了コードは成功（選定保留も含む）が0、実行エラーが1、CLI引数エラーが2です。
自動処理では終了コードだけでなくJSONの `status` を見てください。

## 共通設定

| 環境変数 | CLI引数 | 既定値 |
| --- | --- | --- |
| `ISSUE_MODEL_POLICY` | `--policy` | `balanced` |
| `JEV_MODEL` | `--jev-model` | `jev-latest` |
| `ISSUE_MODEL_CATALOG` | `--catalog` | 同梱カタログ |

CLI引数が環境変数より優先します。Slackプロセスにも同じ設定を適用できます。
Jevのモデル名を固定する場合は、その時点でアカウントから利用できるIDを指定します。

## 他のCodexセッションから使う

このリポジトリにはユーザー共通の `$jev-issue-router` スキルを同梱しています。
CLIをインストールした後、ユーザーのスキルディレクトリへリンクします。

```sh
mkdir -p "$HOME/.agents/skills"
ln -s "$HOME/dev/Github/jev-issue-router/skills/jev-issue-router" \
  "$HOME/.agents/skills/jev-issue-router"
```

既に同名のスキルがある場合は上書きせず、リンク先を確認してください。
clone先が異なる場合は1つ目のパスを変更します。
スキルはリンク先の `.venv/bin/issue-model` を呼ぶため、PATHやプロジェクトごとの設定は不要です。

Codexへの依頼例:

```text
$jev-issue-router このIssueに適した各社のモデルと推論設定を教えて:
https://github.com/OWNER/REPO/issues/123
```

Issue本文を直接渡すこともできます。スキルの説明に合致するモデル選定依頼では自動選択も可能です。
スキルが候補に現れない場合は新しいセッションを開き、必要ならCodexを再起動してください。
登録はこのPC・このユーザーのローカルセッション向けです。クラウドや別のPCでは別途導入が必要です。
各セッションのファイルアクセス・ネットワーク権限は引き続き適用されます。

このスキルは推薦結果を返すだけで、セッションのモデル変更やGitHub/Slack投稿は行いません。
削除は作成したシンボリックリンクだけを取り除きます。repo本体や既存のJev MCP設定は残ります。

参考: [Codexのスキル配置・検出仕様](https://developers.openai.com/codex/skills)。

## 更新・削除

```sh
cd ~/dev/Github/jev-issue-router
git pull --ff-only
.venv/bin/python -m pip install -e .
```

Slackも使っている場合は `-e '.[slack]'` にしてプロセスを再起動します。
削除する場合は起動中のプロセスを停止し、PATHから追加した行を外してcloneしたフォルダを削除します。
macOS Keychain項目は既存Jev連携と共用するため、本ツールの削除だけでは消さないでください。

## よくある問題

| 症状 | 確認すること |
| --- | --- |
| コマンドが見つからない | `.venv/bin/issue-model` を直接実行するかPATHを設定 |
| Jev HTTP 401/403 | APIキー、アカウントのAPI利用権限 |
| Jev HTTP 429 | 利用制限・残高などTypeSafe側の状態。自動再試行はしません |
| GitHub request failed | `gh auth status`、対象repo/Issueの閲覧権限、組織SSO |
| 情報不足・選定保留 | 目的、現状、期待動作、対象範囲、完了条件を追加 |
| 次候補の確率も高い | 判定が分散しています。追加情報や実タスク評価で比較 |
| カタログ確認から30日超 | [カタログ更新手順](architecture.md#カタログを更新する)を実施 |

通信失敗時に成功のような推薦は出しません。APIエラー本文やキーをエラー表示に含めません。
