import SwiftUI

struct ContentView: View {
    @State private var model = AppModel()
    @State private var showSettings = false

    var body: some View {
        NavigationStack {
            Form {
                inputSection
                policySection
                runSection
                noticeSection
            }
            .navigationTitle("Jev Issue Router")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showSettings = true } label: {
                        Label("設定", systemImage: "gearshape")
                    }
                }
            }
            .sheet(isPresented: $showSettings, onDismiss: { model.refreshKeyStatus() }) { SettingsView() }
            .sheet(item: $model.outcome) { ResultView(outcome: $0) }
            .onChange(of: model.draft) { _, _ in model.saveDraft() }
        }
    }

    private var inputSection: some View {
        Section {
            Picker("入力", selection: $model.input) {
                ForEach(AppModel.Input.allCases) { input in
                    Text(input.title).tag(input)
                }
            }
            .pickerStyle(.segmented)

            if model.input == .url {
                TextField("https://github.com/OWNER/REPO/issues/123", text: $model.draft.url)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.URL)
            } else {
                TextEditor(text: $model.draft.body)
                    .frame(minHeight: 130)
                    .overlay(alignment: .topLeading) {
                        if model.draft.body.isEmpty {
                            Text("例: 設定画面の保存ボタンを「変更を保存」に変更し、画面テストを更新する。")
                                .foregroundStyle(.tertiary)
                                .padding(.top, 8)
                                .allowsHitTesting(false)
                        }
                    }
            }

            TextEditor(text: $model.draft.context)
                .frame(minHeight: 70)
                .overlay(alignment: .topLeading) {
                    if model.draft.context.isEmpty {
                        Text("追加コンテキスト（任意）: 対象範囲、完了条件、制約など")
                            .foregroundStyle(.tertiary)
                            .padding(.top, 8)
                            .allowsHitTesting(false)
                    }
                }
        } header: {
            Text("入力")
        } footer: {
            Text(model.input == .url
                 ? "Issueのタイトルと本文をGitHub APIで取得して評価します。GitHubトークンが必要です。"
                 : "タスクやプロンプトの本文から評価します。GitHub認証は不要です。")
        }
    }

    private var policySection: some View {
        Section {
            Picker("方針", selection: $model.draft.policy) {
                ForEach(Policies.names, id: \.self) { name in
                    Text(name).tag(name)
                }
            }
        } header: {
            Text("方針")
        } footer: {
            Text(Policies.descriptions[model.draft.policy] ?? "")
        }
    }

    private var runSection: some View {
        Section {
            Button {
                Task { await model.evaluate() }
            } label: {
                HStack {
                    if model.isEvaluating {
                        ProgressView().padding(.trailing, 6)
                        Text("Jevで評価中…")
                    } else {
                        Text("評価する").fontWeight(.semibold)
                    }
                    Spacer()
                }
            }
            .disabled(!model.canEvaluate)

            Button("入力をクリア", role: .destructive) { model.clearDraft() }
                .disabled(model.draft.isEmpty)

            if let message = model.errorMessage {
                Label(message, systemImage: "exclamationmark.triangle")
                    .foregroundStyle(.red)
                    .font(.footnote)
            }
        }
    }

    @ViewBuilder
    private var noticeSection: some View {
        Section {
            if !model.hasAPIKey {
                Label("TypeSafe APIキーが未設定です。設定から保存してください。", systemImage: "key")
                    .font(.footnote)
            }
            if model.input == .url && !model.hasGitHubToken {
                Label("GitHubトークンが未設定です。設定から保存してください。", systemImage: "link")
                    .font(.footnote)
            }
            Text("入力した本文と追加コンテキストは、評価のためTypeSafeのJev APIへ送信されます。"
                 + "推薦先の各社APIは実行しません。入力内容はこの端末内に自動保存され、次回起動時に復元されます"
                 + "（APIキーと結果は保存しません）。")
            .font(.footnote)
            .foregroundStyle(.secondary)
        }
    }
}

#Preview {
    ContentView()
}
