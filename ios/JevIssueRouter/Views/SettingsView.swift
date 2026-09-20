import SwiftUI

struct SettingsView: View {
    @Environment(\.dismiss) private var dismiss

    @State private var apiKey = ""
    @State private var githubToken = ""
    @State private var apiEntry = Keychain.entry(service: Keychain.typesafeService)
    @State private var githubEntry = Keychain.entry(service: Keychain.githubService)
    @State private var keyMessage: String?
    @State private var keyFailed = false
    @State private var pingMessage = "未確認"
    @State private var pingState: PingState = .unknown
    @State private var isChecking = false

    private enum PingState { case unknown, ok, ng }

    var body: some View {
        NavigationStack {
            Form {
                apiKeySection
                githubSection
                aboutSection
            }
            .navigationTitle("設定")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完了") { dismiss() }
                }
            }
        }
    }

    private var apiKeySection: some View {
        Section {
            LabeledContent("保存状態") {
                Text(apiEntry.exists ? "保存済み\(savedAt(apiEntry))" : "未設定")
                    .foregroundStyle(apiEntry.exists ? .green : .red)
            }
            LabeledContent("疎通") {
                Text(pingMessage)
                    .foregroundStyle(pingState == .ok ? .green : pingState == .ng ? .red : .secondary)
                    .multilineTextAlignment(.trailing)
            }
            SecureField("TypeSafe APIキーを貼り付け", text: $apiKey)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            Button("Keychainに保存") { saveAPIKey() }
                .disabled(apiKey.isEmpty)
            Button("疎通確認") { Task { await check() } }
                .disabled(!apiEntry.exists || isChecking)
            if apiEntry.exists {
                Button("キーを削除", role: .destructive) {
                    Keychain.delete(service: Keychain.typesafeService)
                    apiEntry = Keychain.entry(service: Keychain.typesafeService)
                    pingState = .unknown
                    pingMessage = "未確認"
                    keyMessage = nil
                }
            }
            if let keyMessage {
                Text(keyMessage)
                    .font(.footnote)
                    .foregroundStyle(keyFailed ? .red : .secondary)
            }
        } header: {
            Text("TypeSafe APIキー")
        } footer: {
            Text("キーはこの端末のKeychainにだけ保存します（iCloud同期なし）。保存後に表示する機能はありません。"
                 + "疎通確認は、保存済みのキーでJev APIへごく小さな固定の問い合わせを1回送ります"
                 + "（わずかな利用量が発生。入力内容は送りません）。")
        }
    }

    private var githubSection: some View {
        Section {
            LabeledContent("保存状態") {
                Text(githubEntry.exists ? "保存済み\(savedAt(githubEntry))" : "未設定")
                    .foregroundStyle(githubEntry.exists ? .green : .secondary)
            }
            SecureField("Personal access token", text: $githubToken)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            Button("Keychainに保存") { saveGitHubToken() }
                .disabled(githubToken.isEmpty)
            if githubEntry.exists {
                Button("トークンを削除", role: .destructive) {
                    Keychain.delete(service: Keychain.githubService)
                    githubEntry = Keychain.entry(service: Keychain.githubService)
                }
            }
        } header: {
            Text("GitHubトークン（Issue URLの読み込み用）")
        } footer: {
            Text("iOSでは gh コマンドが使えないため、Issueの取得にはトークンが必要です。"
                 + "対象リポジトリのIssueを読める最小限の権限（fine-grained token の Issues: Read）で十分です。"
                 + "タスク本文を直接入力する場合は不要です。")
        }
    }

    private var aboutSection: some View {
        Section {
            LabeledContent("カタログ", value: catalogSummary)
            LabeledContent("方針バージョン", value: Router.policyVersion)
        } header: {
            Text("このアプリについて")
        } footer: {
            Text("CLIとmacOSアプリと同じ評価ロジックをSwiftへ移植したものです。"
                 + "推薦するモデルのAPIは実行しません。リポジトリの状態を判断材料に加える機能は、"
                 + "端末にチェックアウトが無いためiOS版にはありません。")
        }
    }

    private var catalogSummary: String {
        guard let catalog = try? Catalog.bundled() else { return "読み込めません" }
        return "\(catalog.version)（確認日 \(catalog.verifiedAtText)）"
    }

    private func savedAt(_ entry: Keychain.Entry) -> String {
        guard let date = entry.savedAt else { return "" }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd HH:mm"
        return "（\(formatter.string(from: date)) 保存）"
    }

    private func saveAPIKey() {
        do {
            try Keychain.save(apiKey, service: Keychain.typesafeService)
            apiKey = ""
            apiEntry = Keychain.entry(service: Keychain.typesafeService)
            keyFailed = false
            keyMessage = "保存しました。"
            Task { await check() }
        } catch let error as RouterError {
            keyFailed = true
            keyMessage = error.message
        } catch {
            keyFailed = true
            keyMessage = "Keychainへの保存に失敗しました"
        }
    }

    private func saveGitHubToken() {
        do {
            try Keychain.save(githubToken, service: Keychain.githubService)
            githubToken = ""
            githubEntry = Keychain.entry(service: Keychain.githubService)
        } catch let error as RouterError {
            keyFailed = true
            keyMessage = error.message
        } catch {
            keyFailed = true
            keyMessage = "Keychainへの保存に失敗しました"
        }
    }

    private func check() async {
        guard let key = Keychain.read(service: Keychain.typesafeService) else { return }
        isChecking = true
        pingState = .unknown
        pingMessage = "確認中…"
        do {
            let result = try await JevClient(apiKey: key).check()
            pingState = .ok
            pingMessage = "OK — \(result.model)（\(result.checkedAt) 確認）"
        } catch let error as RouterError {
            pingState = .ng
            pingMessage = error.message
        } catch {
            pingState = .ng
            pingMessage = "NG — 確認できませんでした"
        }
        isChecking = false
    }
}

#Preview {
    SettingsView()
}
