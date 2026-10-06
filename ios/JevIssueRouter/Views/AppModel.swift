import Foundation
import Observation

struct Outcome: Identifiable {
    let id = UUID()
    let result: JSONValue
    let text: String
    var status: String { result["status"]?.stringValue ?? "" }
}

@MainActor
@Observable
final class AppModel {
    enum Input: String, CaseIterable, Identifiable {
        case url, body
        var id: String { rawValue }
        var title: String { self == .url ? "Issue URL" : "タスク本文" }
    }

    var input: Input = .body
    var draft = DraftStore.load()
    private(set) var settings = SettingsStore.load()
    var outcome: Outcome?
    var errorMessage: String?
    var isEvaluating = false

    private(set) var hasAPIKey = Keychain.entry(service: SettingsStore.load().keychainService).exists
    private(set) var hasGitHubToken = Keychain.entry(service: Keychain.githubService).exists

    /// "Jev" or "Clef", for the notices and the progress text.
    var evaluatorLabel: String { settings.label }

    /// Called when the settings sheet closes, so the notices reflect what was just saved, chosen or deleted.
    func refreshKeyStatus() {
        settings = SettingsStore.load()
        hasAPIKey = Keychain.entry(service: settings.keychainService).exists
        hasGitHubToken = Keychain.entry(service: Keychain.githubService).exists
    }

    var canEvaluate: Bool {
        guard !isEvaluating else { return false }
        return input == .url
            ? !draft.url.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            : !draft.body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    func saveDraft() {
        DraftStore.save(draft)
    }

    func clearDraft() {
        draft = Draft()
        DraftStore.clear()
        errorMessage = nil
    }

    func evaluate() async {
        errorMessage = nil
        refreshKeyStatus()
        let evaluator: Evaluator
        do {
            evaluator = try settings.makeEvaluator()  // before GitHub or the evaluator is contacted
        } catch let error as RouterError {
            errorMessage = error.message + "。右上の設定を確認してください。"
            return
        } catch {
            errorMessage = "評価モデルの設定を確認してください。"
            return
        }
        guard let key = Keychain.read(service: evaluator.keychainService) else {
            errorMessage = (evaluator.name == "jev" ? "TypeSafe APIキー" : "Cloudflare APIトークン")
                + "が未設定です。右上の設定から保存してください。"
            return
        }
        isEvaluating = true
        defer { isEvaluating = false }
        do {
            let catalog = try Catalog.bundled()
            var title = "", body = ""
            if input == .url {
                guard let token = Keychain.read(service: Keychain.githubService) else {
                    throw RouterError("GitHubトークンが未設定です。設定から保存するか、タスク本文を入力してください。")
                }
                let issue = try await GitHubClient(token: token).fetchIssue(url: draft.url)
                (title, body) = (issue.title, issue.body)
            } else {
                body = draft.body
            }
            let issue = try Router.normalizeIssue(title: title, body: body, context: draft.context)
            let client = SystemOneClient(evaluator: evaluator, token: key)
            let result = try await Router.route(issue: issue, catalog: catalog, policy: draft.policy,
                                                evaluator: evaluator) { request in
                try await client.evaluate(request)
            }
            outcome = Outcome(result: result, text: Render.text(result))
        } catch let error as RouterError {
            errorMessage = error.message
        } catch {
            errorMessage = "評価に失敗しました。時間をおいて再試行してください。"
        }
    }
}
