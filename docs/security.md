# GitHub Securityの運用

## 方針

無料で利用できる範囲で、検知を先に導入します。AI Agent、bot、人のブランチ作成・
PR更新・mainへの既存更新フローを維持し、承認人数や必須チェックを勝手に追加しません。
公開設定の変更はセキュリティ機能の有効化とは別の判断です。

2026-09-19の導入時点ではprivateです。Dependabot alerts/security updatesを有効化し、
Actions既定権限をreadへ変更しました。既存workflowは必要な権限を明示済みです。
ActionsによるPR作成・承認の許可と、各GitHub Appの権限は変更していません。
CodeQL、Secret Scanning、Push Protection、PVRは無料で使えるpublic化後に設定します。
有料のAdvanced Security/Code Security/Secret Protectionは有効化していません。

## gh-secureの安全な使い方

導入時の検証対象はGitHubSecurityLab/gh-secure 1.0.0、commit
`42c928f94b61caae03774d2436b897a1d04fff20`です。
更新時はREADMEと実装を再確認してください。

```sh
gh secure --version
gh secure --help
gh secure status --repo buckmoon/jev-issue-router
gh secure --repo buckmoon/jev-issue-router --yes --dry-run
```

statusはAPI取得失敗も「未有効」と表示します。403/404の実応答と照合してください。
dry-runは設定の可用性を実際に検証せず、予定する変更を表示します。
Branch Protectionの選択は承認1件、古い承認の無効化、会話解決必須などを追加します。
既存保護があればスキップしますが、取得エラーとの区別や詳細な差分検査はありません。
Rulesetsがあれば警告しますが、適用ブランチ・継承・内容の実査は別途必要です。
CodeQLのdefault setupは既存advanced workflowを無効化するため、横展開時は特に確認します。

## 公開後の有効化

管理者が可視性・保護ルール・既存CodeQL構成を再確認し、変更前設定を保存してから実行します。
以下は実行手順であり、このファイルを追加しても設定は変わりません。

```sh
gh repo view buckmoon/jev-issue-router --json visibility,defaultBranchRef
gh api 'repos/buckmoon/jev-issue-router/rulesets?includes_parents=true'
gh api repos/buckmoon/jev-issue-router/branches/main/protection
gh api repos/buckmoon/jev-issue-router/code-scanning/default-setup
gh secure --repo buckmoon/jev-issue-router secret-scanning vulnerability-reporting code-scanning --yes --dry-run
```

publicであること、既存advanced CodeQLがないこと、追加課金が不要なことを確認します。
Secret Scanning本体がdisabledなら先に本体を有効化します。gh-secure 1.0.0の
secret-scanning機能は本体の状態を確認せず、Push ProtectionのみをPATCHする実装です。

```sh
gh api --method PATCH repos/buckmoon/jev-issue-router --input - <<'JSON'
{"security_and_analysis":{"secret_scanning":{"status":"enabled"}}}
JSON
gh secure --repo buckmoon/jev-issue-router secret-scanning vulnerability-reporting code-scanning --yes
gh secure status --repo buckmoon/jev-issue-router
gh api repos/buckmoon/jev-issue-router --jq .security_and_analysis
gh api repos/buckmoon/jev-issue-router/code-scanning/default-setup
gh api repos/buckmoon/jev-issue-router/code-scanning/analyses
gh run list --repo buckmoon/jev-issue-router
```

CodeQLの設定成功と解析成功は別です。解析runの完了、対象言語と結果まで確認します。
Push Protectionは実在する秘密を使ってテストしません。検知対象の秘密が含まれるpushは
人・AI Agent・botいずれも停止する可能性があります。正常なコードのpushやPRは維持します。

## Dependency reviewと更新bot

Dependency reviewはpublic時のpull_requestでだけ動き、read権限、SHA固定、
`warn-only: true`で結果を表示します。PRコメント投稿や必須チェック化はしません。
private時はskipします。API障害などによる実行失敗もあり得ますが、必須チェックにはしません。

Dependabot security updatesは脆弱性修正PRを作りますが、自動マージしません。
有効化後のGraph Update完了後、SBOMにはActionsに加え、`slack-bolt`、`build`、
`ruff`、`setuptools`が登録されたことを確認しました。導入直後のスナップショットだけで
欠落と判断しないでください。推移的依存や各環境の解決済みバージョンまでの網羅は未確認です。
さらに正確にカバーするには、実際のインストールに対応したlockfile/依存送信を別途検証します。

組織にはselected repositories向けのRenovateが存在します。対象リポジトリへの割当は
現在の認証では確認できなかったため、Dependabot version updatesは未追加です。
Renovateの対象・スケジュール・更新範囲を確認してから役割を分けて導入してください。
CODEOWNERSも自動レビュー依頼の担当者が合意されるまで追加しません。

## ロールバック

設定変更前のAPI応答を保管し、今回変更した項目だけを戻します。
今回の初期状態へ戻す場合のコマンドです。後日の設定変更を上書きしないよう先に比較してください。

```sh
gh api --method DELETE repos/buckmoon/jev-issue-router/automated-security-fixes
gh api --method DELETE repos/buckmoon/jev-issue-router/vulnerability-alerts
gh api --method PUT repos/buckmoon/jev-issue-router/actions/permissions/workflow \
  -f default_workflow_permissions=write -F can_approve_pull_request_reviews=true
```

ファイル変更は対応するコミットをrevertします。既に開いたbot PRや通知は設定を戻しても
取り消されません。履歴・公開済みコピー・漏洩した秘密も設定のロールバックでは回収できません。

## 公式資料

- [gh-secure](https://github.com/GitHubSecurityLab/gh-secure)
- [GitHub Security設定](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-security-and-analysis-settings-for-your-repository)
- [CodeQL default setupによる既存設定への影響](https://docs.github.com/en/code-security/reference/code-scanning/troubleshoot-analysis-errors/two-codeql-workflows)
- [Dependency review](https://docs.github.com/en/code-security/concepts/supply-chain-security/dependency-review)
