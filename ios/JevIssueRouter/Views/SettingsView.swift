import SwiftUI

struct SettingsView: View {
    @Environment(\.dismiss) private var dismiss

    @State private var apiKey = ""
    @State private var githubToken = ""
    @State private var settings = SettingsStore.load()
    @State private var settingsError: String?
    @State private var apiEntry = Keychain.entry(service: SettingsStore.load().keychainService)
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
                evaluatorSection
                if settings.evaluator == "clef" {
                    clefSection
                }
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

    private var evaluatorSection: some View {
        Section {
            Picker("評価モデル", selection: $settings.evaluator) {
                Text("Jev（TypeSafe）").tag("jev")
                Text("Clef（Cloudflare Workers AI）").tag("clef")
            }
            .onChange(of: settings.evaluator) { _, _ in
                saveSettings()
                apiKey = ""
                apiEntry = Keychain.entry(service: settings.keychainService)
                resetPing()
                keyMessage = nil
            }
            if let settingsError {
                Text("設定を保存できません: " + settingsError)
                    .font(.footnote)
                    .foregroundStyle(.red)
            }
        } header: {
            Text("評価モデル")
        } footer: {
            Text(settings.evaluator == "clef"
                 ? "Issueの判定をCloudflare Workers AIのClefで行います（Cloudflareの利用料が発生）。"
                    + "評価軸・方針はJevで動作確認したもので、Clefでは未校正です。"
                    + "このMac内のサーバー（Ollama等）はiOSからは使えません。"
                 : "Issueの判定をTypeSafeのJevで行います。")
        }
    }

    private var clefSection: some View {
        Section {
            TextField("アカウントID（32桁の16進数）", text: $settings.cloudflareAccountID)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .onChange(of: settings.cloudflareAccountID) { _, _ in saveSettings() }
            HStack {
                presetButton("精度優先", select: "clef", assess: "")
                presetButton("高速", select: "clef-flash", assess: "")
                presetButton("段階分け", select: "clef", assess: "clef-flash")
            }
            Picker("選定段階のモデル", selection: $settings.clefModel) {
                ForEach(Evaluator.workersAIModels, id: \.self) { Text($0).tag($0) }
            }
            .onChange(of: settings.clefModel) { _, _ in saveSettings() }
            Picker("評価段階のモデル", selection: $settings.clefAssessModel) {
                Text("選定段階と同じ").tag("")
                ForEach(Evaluator.workersAIModels, id: \.self) { Text($0).tag($0) }
            }
            .onChange(of: settings.clefAssessModel) { _, _ in saveSettings() }
        } header: {
            Text("Cloudflare Workers AI")
        } footer: {
            Text("精度優先は clef / clef、高速は clef-flash / clef-flash、段階分けは評価段階 clef-flash → 選定段階 clef です。"
                 + "使い分けは校正前の目安です。アカウントIDは結果に含めません。")
        }
    }

    private func presetButton(_ title: String, select: String, assess: String) -> some View {
        Button(title) {
            settings.clefModel = select
            settings.clefAssessModel = assess
        }
        .buttonStyle(.bordered)
        .frame(maxWidth: .infinity)
    }

    private var keyName: String { settings.evaluator == "clef" ? "Cloudflare APIトークン" : "TypeSafe APIキー" }

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
            SecureField(keyName + "を貼り付け", text: $apiKey)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
            Button("Keychainに保存") { saveAPIKey() }
                .disabled(apiKey.isEmpty)
            Button("疎通確認") { Task { await check() } }
                .disabled(!apiEntry.exists || isChecking || settingsError != nil)
            if apiEntry.exists {
                Button(settings.evaluator == "clef" ? "トークンを削除" : "キーを削除", role: .destructive) {
                    Keychain.delete(service: settings.keychainService)
                    apiEntry = Keychain.entry(service: settings.keychainService)
                    resetPing()
                    keyMessage = nil
                }
            }
            if let keyMessage {
                Text(keyMessage)
                    .font(.footnote)
                    .foregroundStyle(keyFailed ? .red : .secondary)
            }
        } header: {
            Text(keyName)
        } footer: {
            Text("キーはこの端末のKeychainにだけ保存します（iCloud同期なし）。保存後に表示する機能はありません。"
                 + (settings.evaluator == "clef" ? "トークンは対象アカウントのWorkers AI権限だけに絞ってください。" : "")
                 + "疎通確認は、選択中の評価モデルへごく小さな固定の問い合わせを送ります"
                 + "（段階でモデルが違えば各1回。わずかな利用量が発生。入力内容は送りません）。")
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
            LabeledContent("評価モデル", value: settingsSummary)
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

    private var settingsSummary: String {
        guard let evaluator = try? settings.makeEvaluator() else { return "未設定" }
        let models = evaluator.distinctModels.joined(separator: " → ")
        return "\(evaluator.label) (\(evaluator.host) / \(models))"
    }

    private func saveSettings() {
        do {
            try SettingsStore.save(settings)
            settingsError = nil
        } catch let error as RouterError {
            settingsError = error.message
        } catch {
            settingsError = "設定を保存できません"
        }
        resetPing()
    }

    private func resetPing() {
        pingState = .unknown
        pingMessage = "未確認"
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
            try Keychain.save(apiKey, service: settings.keychainService)
            apiKey = ""
            apiEntry = Keychain.entry(service: settings.keychainService)
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
        guard let evaluator = try? settings.makeEvaluator(),
              let key = Keychain.read(service: evaluator.keychainService) else { return }
        isChecking = true
        pingState = .unknown
        pingMessage = "確認中…"
        do {
            let result = try await SystemOneClient(evaluator: evaluator, token: key).check()
            pingState = .ok
            pingMessage = "OK — \(result.models.joined(separator: ", "))（\(result.checkedAt) 確認）"
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
