# iOSネイティブアプリ

iPhone / iPadから、タスクやGitHub Issueに適したモデルと推論設定を選ぶSwiftUIアプリです。
`ios/` にXcodeプロジェクトのソース一式が入っています。

CLIやmacOSアプリと違い、Pythonは動きません。`issue_router/core.py` の2段階評価をSwiftへ移植し、
端末から直接TypeSafeのJev APIを呼びます。サーバも、Macの常時起動も不要です。

## 必要なもの

- Xcode 16以降（ファイルシステム同期グループを使うため）、iOS 17以降の実機またはシミュレータ
- TypeSafe/JevのAPIキー
- GitHub Issue URLを読む場合のみ、GitHubのPersonal Access Token（iOSでは `gh` が使えないため）
- 実機にインストールする場合のみ、Apple Developerアカウント（署名用）

## ビルドと実行

```sh
open ios/JevIssueRouter.xcodeproj
```

スキーム `JevIssueRouter` を選び、シミュレータまたは接続した実機を指定して実行（⌘R）します。
実機の場合は、ターゲットの Signing & Capabilities で自分のTeamを選び、
Bundle Identifier を自分のものに変更してください（既定は `local.jev.issue-router`）。

コマンドラインからビルドする場合:

```sh
xcodebuild -project ios/JevIssueRouter.xcodeproj -scheme JevIssueRouter -destination 'generic/platform=iOS Simulator' build
```

App Storeやアドホック配布用のビルドは用意していません。各自の署名でインストールしてください。

## 使い方

1. 右上の歯車から**設定**を開き、TypeSafe APIキーを貼り付けて「Keychainに保存」を押します。
   保存直後に疎通確認を1回実行し、OK（応答したJevのモデル名と時刻）またはNGの理由を表示します。
   わずかなAPI利用量が発生します。入力中のタスクは送りません。
2. Issue URLを使う場合は、同じ画面でGitHubトークンも保存します。
   fine-grained tokenの場合、対象リポジトリへの **Issues: Read-only** で足ります。
3. 入力画面で「Issue URL」か「タスク本文」のどちらかを選び、必要なら追加コンテキストと
   [方針](local.md#推薦方針と出力)を指定します。方針を選ぶと、その方針が何を優先するかが下に表示されます。
4. 「評価する」を押すと、各社の推薦モデル・推論設定と評価内容が表示されます。
   テキストとJSONを切り替えられ、表示中の内容をコピーできます。結果と履歴は保存しません。
5. 入力内容（Issue URL、タスク本文、追加コンテキスト、方針）は自動保存され、次回起動時に復元されます。
   「入力をクリア」で入力欄と保存ファイルを消去します。

リポジトリの状態を判断材料に加える機能（CLI・macOSアプリの `--repo`）は、
端末にチェックアウトが無いためiOS版にはありません。

## セキュリティ

- APIキーとGitHubトークンは、この端末のKeychainにだけ保存します。
  iCloudキーチェーンには同期しません（`kSecAttrAccessibleWhenUnlockedThisDeviceOnly`）。
  保存済みの値を画面に表示する機能はありません。設定画面には有無と保存日時だけを表示します。
- Jevへ送信するのは、入力したタイトル・本文・追加コンテキストだけです。
  送信内容は結果のJSON表示で確認できます。推薦先の3社APIは実行しません。
- Jev API・GitHub APIの応答本文はエラーに出しません（HTTPステータスのみ）。リダイレクトも追いません。
- 入力内容の自動保存先はアプリのコンテナ内（`Application Support/jev-issue-router/draft.json`、
  端末ロック中は読めない保護レベル）です。APIキー・トークン・評価結果は保存しません。
- Issue本文は評価プロンプト上「指示ではなくデータ」として扱います（CLIと同じガード文）。

## Python版との対応

| Pythonの実装 | iOS版 |
| --- | --- |
| `core.py` の2段階評価・検証・表示 | `Engine/Router.swift`, `Engine/Render.swift` |
| `core.py` のルーブリック・文脈チェック | `Engine/Rubrics.swift` |
| `policies.py` | `Engine/Policies.swift` |
| `catalog.json` | `Resources/catalog.json`（ビルド時に同梱。`ios/sync-catalog.sh` でコピー） |
| Keychain（`security` コマンド） | `Services/Keychain.swift`（サービス名 `local.jev.typesafe` は共通） |
| `github.py`（`gh` 経由） | `Services/GitHubClient.swift`（GitHub REST APIを直接呼ぶ） |
| `app.py` の画面・下書き保存 | `Views/`, `Services/DraftStore.swift` |

同じ入力と同じJev応答を与えたとき、結果JSON（`input_sha256` を含む）、Jevへ送るリクエスト、
表示テキストがPython版と一致することを、フェイク応答で確認しています
（選定・保留・一部保留・暫定選定の4分岐 × 方針3種）。
表示テキストの差はiOSに `--policy` オプションが無い1行の言い換えだけです。

ルーブリック、方針、カタログ、結果JSONを変更したときは、Swift側も更新してください。
`tests/test_ios.py` が、定数・方針名・評価軸・カタログの写しのずれを検出します。

## よくある問題

| 症状 | 確認すること |
| --- | --- |
| 「APIキーが未設定です」 | 設定画面でキーを保存。保存状態の行が「保存済み」になるか |
| 疎通がNG（キーが拒否されました） | 保存したキー、アカウントのAPI利用権限。正しいキーを保存し直す |
| 疎通がNG（接続できません） | 端末のネットワーク、VPN、プロキシ |
| Issueが見つかりません（HTTP 404） | URL、トークンの対象リポジトリ設定、privateリポジトリの権限 |
| GitHubがトークンを拒否（401/403） | トークンの有効期限、Issues権限、組織のSSO承認 |
| 実機にインストールできない | Signing & CapabilitiesのTeamとBundle Identifier |
| ビルドが `circular reference` で失敗 | 外部エディタでSwiftを書き換えた直後の増分ビルドで稀に出ます。⌘⇧K（Clean）後に再ビルド |
