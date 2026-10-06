# macOSデスクトップアプリ

評価モデルの選択とAPIキーの保存、タスク・プロンプトの入力、結果の表示を1つの画面で行う簡易アプリです。
`Jev Issue Router.app` として専用ウィンドウで開きます。ブラウザは使いません。
ウィンドウの中身は、このMac内だけで動くローカル画面をmacOS標準のWebKitで表示したものです。
CLIと同じ評価エンジンを使います。追加の依存ライブラリはありません。

`.app` の作成とKeychainへのキー保存はmacOS専用です。他のOSでは `issue-model-app` が同じ画面をブラウザに開きますが、
キーは `TYPESAFE_API_KEY`（Clefは `CLOUDFLARE_API_TOKEN`）環境変数で渡してください（未検証）。

## 必要なもの

- macOS、Python 3.10以降（`python3 --version` で確認。無ければ `brew install python` など）
- 評価モデルの利用手段のいずれか（[評価モデルと認証](local.md#評価モデルと認証)）
  - TypeSafe/JevのAPIキー（既定）
  - Clef（Cloudflare Workers AI）: CloudflareのアカウントIDとWorkers AI権限のAPIトークン
  - Clef（このMac内のサーバー）: Ollama 0.35.1以降などのSystem Oneサーバーと、取得済みのClefモデル
- GitHub Issue URLを読む場合のみ、GitHub CLI `gh` と `gh auth login`

## インストール

```sh
mkdir -p ~/dev/Github
cd ~/dev/Github
git clone https://github.com/buckmoon/jev-issue-router.git
cd jev-issue-router
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/issue-model-app --install-mac-app
```

最後のコマンドが `~/Applications/Jev Issue Router.app` を作成します。
FinderのホームフォルダにあるApplications、またはSpotlightで「Jev Issue Router」を検索して起動します。
Dockに置く場合は、起動前にFinderからDockへドラッグしてください。

アプリはこのcloneの `.venv` を参照します。フォルダを移動・削除した場合は、
新しい場所で `--install-mac-app` を再実行してください。
配布用の署名済みアプリ・dmgは提供していません。アプリはmacOS標準の `osacompile` でこのPC上に生成する
小さなアプリです。Intel / Apple Silicon両対応のユニバーサルバイナリで、Rosettaは不要です。
生成後にこのPC上でad-hoc署名します（Apple Developer IDによる署名・公証ではありません）。
macOSの設定により起動時に確認が表示された場合は、内容を確認のうえ許可するか、
後述のターミナルからの起動（ブラウザ表示）を使ってください。

## 使い方

1. 起動するとアプリのウィンドウが開きます。
2. **評価モデルとAPIキー**: 先頭の「評価モデル」で、Issueを判定するモデルを選びます。選択は自動で保存され、次回起動時も使われます。

   | 選択 | 入力するもの |
   | --- | --- |
   | Jev（TypeSafe）（既定） | TypeSafe APIキー |
   | Clef（Cloudflare Workers AI） | CloudflareアカウントID（32桁の16進数）、Cloudflare APIトークン、モデル（下記） |
   | Clef（このMac内のサーバー） | サーバーのURL（空なら `http://127.0.0.1:11434/v1/systemone`）、モデル（下記）。キーは不要 |

   - **キー**: 初回だけ貼り付けて「Keychainに保存」を押します。CLIと同じKeychain項目
     （Jevはサービス `local.jev.typesafe`、Clefは `local.clef.cloudflare`）に保存し、既存の項目があれば上書きします。
     `TYPESAFE_API_KEY` / `CLOUDFLARE_API_TOKEN` 環境変数がある場合はそちらが優先されます。
     CloudflareのトークンはWorkers AIの権限だけに絞ってください。
   - **モデル（Clef）**: 「選定段階のモデル」と「評価段階のモデル（空なら選定段階と同じ）」の2欄です。
     Workers AIでは「使い分け」のボタンで埋められます: 精度優先（clef / clef。既定）、高速（clef-flash / clef-flash）、
     段階分け（評価段階 clef-flash → 選定段階 clef）。使い分けの目安は[ローカル手順](local.md#clef-と-clef-flash-の使い分け)を参照してください。
     このMac内のサーバーではOllamaのタグ（例: `clef:27b-q8_0`）も指定できます。メモリの目安は clef-flash 約12GB、clef 約18GB〜です。
   - アカウントID・URL・モデル名が正しくない場合は「設定を保存できません」と表示し、保存しません。
     このMac内のサーバーのURLは、loopbackのhttp（127.0.0.1など）かhttpsだけ使えます。

   評価モデルの欄には2つの状態が表示されます。
   - **保存状態**: 選択中の評価モデルのキーがKeychainに保存済みか未設定か、保存（最終更新）日時、環境変数を使用中かどうか。
     Keychain項目の属性だけを読み、キーの値は読みません。
   - **疎通**: 「疎通確認」を押すと、選択中の評価モデルへ小さな固定の問い合わせを送り、
     OK（応答したモデル名と確認時刻。例: 「OK — clef-flash, clef（14:02 確認）」）またはNGの理由
     （キーの拒否、利用制限、接続不可など）を表示します。評価段階と選定段階でモデルが違う場合は、それぞれに1回ずつ送ります。
     キーの保存直後にも自動で実行します。わずかなAPI利用量が発生します（このMac内のサーバーを除く）。入力中のタスクは送りません。
3. **入力**: GitHub Issue URL、またはタスク・プロンプトの本文のどちらか一方を入力します。
   必要なら追加コンテキストと[方針](local.md#推薦方針と出力)を指定します。
   方針を選ぶと、その方針が何を優先するかの説明が選択欄の下に表示されます。
   **リポジトリのフォルダ**を指定すると（「選択…」でフォルダを選ぶか、パスを入力）、
   その[リポジトリの状態](local.md#リポジトリの状態を判断材料に加える)も判断材料に加えます。
4. 「評価する」を押すと、選択中の評価モデルで評価し、各社の推薦モデル・推論設定と評価内容が表示されます。
   結果の最後に、使った評価モデルとモデル名（例: 「評価モデル: Clef (workers-ai / clef-flash → clef)」）が出ます。
   Clefの結果には「未校正」の警告が付きます。
   JSON表示への切り替えとコピーができます。結果と履歴は保存しません。
5. 入力内容（Issue URL、タスク本文、追加コンテキスト、リポジトリのフォルダ、方針）は自動保存され、
   次回起動時に復元されます。「入力をクリア」を押すと入力欄と保存ファイルを消去します（評価モデルの設定は残ります）。

ターミナルから起動することもできます。この場合は同じ画面が既定のブラウザに開きます。

```sh
.venv/bin/issue-model-app
```

## 終了

ウィンドウを閉じるか ⌘Q で終了します。画面を提供しているバックグラウンドのプロセスも一緒に終了します。
ウィンドウを開いている間は、長時間放置しても使い続けられます。バックグラウンドのプロセスが何らかの理由で止まった場合は、
アプリが10〜20秒ほどで自動的に起動し直して画面を読み込み直します（入力内容は自動保存から復元、表示中の結果は消えます）。
ターミナルから起動した場合は Ctrl+C で終了します。ブラウザのタブを閉じた場合も約10分後に自動で終了します。

## セキュリティ

- ウィンドウに表示する画面は `127.0.0.1` のランダムなポートでのみ待ち受け、他のPCからは接続できません。
- 起動ごとのトークンとHostヘッダを検証し、他のWebサイトからの操作を拒否します。
- キー・トークンはKeychainだけに保存します。ファイル、ブラウザの保存領域、ログ、プロセス引数には残しません。
  保存済みのキーを画面に表示する機能はありません。
- 入力内容の自動保存先は、このMac内の `~/Library/Application Support/jev-issue-router/draft.json` です
  （本人だけが読み書きできる権限。macOS以外は `~/.config/jev-issue-router/`）。
  APIキーと評価結果は保存しません。機密のタスク文を残したくない場合は、終了前に「入力をクリア」を押してください。
- 評価モデルの設定は同じフォルダの `settings.json` に保存します（本人だけが読み書きできる権限）。
  内容は評価モデル・ホスト・モデル名・URL・CloudflareアカウントIDだけで、キーやトークンは含みません。
- 入力したタスク本文・コンテキストは、評価のため選択中の評価モデルへ送信されます。画面の注意書きも選択に合わせて切り替わります。

  | 評価モデル | 送信先 |
  | --- | --- |
  | Jev（TypeSafe） | TypeSafeのJev API |
  | Clef（Cloudflare Workers AI） | Cloudflare Workers AI（Cloudflareの利用料が発生） |
  | Clef（このMac内のサーバー） | 指定したサーバー。既定の127.0.0.1なら外部へは送信しません |

- リポジトリを指定した場合は、構成・Gitの状態・パス名・コミット件名などのメタデータも送信されます。
  ファイルの中身は読みません。送信した内容は結果のJSON表示の `repository` で確認できます。

## 更新・削除

```sh
cd ~/dev/Github/jev-issue-router
git pull --ff-only
.venv/bin/python -m pip install .
.venv/bin/issue-model-app --install-mac-app
```

`pip install .` はソースのコピーをインストールするため、`git pull` だけでは更新されません。必ず再実行してください。

削除は `~/Applications/Jev Issue Router.app` をゴミ箱へ移動し、
保存された入力内容と設定 `~/Library/Application Support/jev-issue-router` を削除します。
Keychain項目は他のJev連携やCLIと共用のため、自動では削除しません。Clefのトークンが不要になった場合は、
「キーチェーンアクセス」でサービス `local.clef.cloudflare` の項目を削除し、Cloudflare側でもトークンを無効にしてください。

## よくある問題

| 症状 | 確認すること |
| --- | --- |
| Rosettaのインストールを求められる | 古い版で作成したアプリです。更新後に `--install-mac-app` を再実行 |
| ブラウザで開いてしまう | 古い版で作成したアプリです。更新後に `--install-mac-app` を再実行 |
| 「アプリとの通信に失敗しました」と出る | 古い版では、ウィンドウを隠したまま約10分たつと裏のプロセスが終了していました。更新後に `--install-mac-app` を再実行。現行版は自動復旧します |
| 起動しても画面が開かない | ターミナルで `.venv/bin/issue-model-app` を実行しエラーを確認。cloneを移動した場合は再インストール |
| Keychainへの保存に失敗 | macOSの許可ダイアログで許可。ログインキーチェーンがロックされていないか確認 |
| GitHub request failed | `gh auth status`。ghがHomebrew以外の場所にある場合はターミナルから起動 |
| 疎通がNG（キーが拒否されました）／Jev HTTP 401/403 | 保存したキー、アカウントのAPI利用権限。正しいキーを保存し直す |
| 疎通がNG（接続できません） | ネットワーク、プロキシ、VPN |
| 「設定を保存できません: Set CLOUDFLARE_ACCOUNT_ID」 | アカウントIDが32桁の16進数（小文字）になっているか |
| 疎通がNG（Clef HTTP 401/403） | Cloudflareトークンの値、Workers AI権限、トークンとアカウントIDが同じアカウントのものか |
| 疎通がNG（Cloudflare error codes …） | Workers AIが失敗を返した状態。数値コードだけを表示します |
| 疎通がNG（Clefサーバーに接続できません） | Ollama等が起動しているか、URL、モデルを `ollama pull` 済みか。初回はモデルの読み込みに時間がかかります |
