import Foundation

/// Reads an Issue through the GitHub REST API. iOS has no `gh` CLI, so the app uses a personal access
/// token from the Keychain. Response bodies are never surfaced in errors.
struct GitHubClient {
    var token: String

    /// Same shape the Python engine accepts: https://github.com/OWNER/REPO/issues/NUMBER
    static func parse(_ url: String) throws -> (repo: String, number: Int) {
        func invalid() -> RouterError {
            RouterError("https://github.com/OWNER/REPO/issues/NUMBER の形式で入力してください")
        }
        var text = url.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.hasSuffix("/") { text.removeLast() }
        guard text.hasPrefix("https://github.com/") else { throw invalid() }
        let parts = text.dropFirst("https://github.com/".count).split(separator: "/", omittingEmptySubsequences: false)
        guard parts.count == 4, parts[2] == "issues" else { throw invalid() }
        let owner = String(parts[0]), repository = String(parts[1]), number = String(parts[3])
        let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "_.-"))
        guard !owner.isEmpty, !repository.isEmpty,
              owner.unicodeScalars.allSatisfy(allowed.contains),
              repository.unicodeScalars.allSatisfy(allowed.contains),
              let issueNumber = Int(number), issueNumber > 0, !number.hasPrefix("0") else {
            throw invalid()
        }
        return (repo: "\(owner)/\(repository)", number: issueNumber)
    }

    func fetchIssue(url: String) async throws -> (title: String, body: String) {
        let (repo, number) = try Self.parse(url)
        guard let endpoint = URL(string: "https://api.github.com/repos/\(repo)/issues/\(number)") else {
            throw RouterError("Issue URLを解釈できませんでした")
        }
        var request = URLRequest(url: endpoint, timeoutInterval: 30)
        request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        request.setValue("2022-11-28", forHTTPHeaderField: "X-GitHub-Api-Version")
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await URLSession.shared.data(for: request, delegate: NoRedirect())
        } catch {
            throw RouterError("GitHubに接続できませんでした。ネットワークを確認してください")
        }
        if let http = response as? HTTPURLResponse, !(200...299).contains(http.statusCode) {
            throw RouterError(Self.failure(http.statusCode))
        }
        guard let json = try? JSONValue.decode(data), let title = json["title"]?.stringValue else {
            throw RouterError("GitHubの応答形式が想定と異なります")
        }
        guard json["pull_request"] == nil else {
            throw RouterError("Pull Requestには対応していません。Issueを指定してください")
        }
        return (title: title, body: json["body"]?.stringValue ?? "")
    }

    private static func failure(_ status: Int) -> String {
        switch status {
        case 401, 403:
            return "GitHubがトークンを拒否しました（HTTP \(status)）。トークンとリポジトリ権限を確認してください"
        case 404:
            return "Issueが見つかりません（HTTP 404）。URLと、そのリポジトリを読む権限を確認してください"
        case 429:
            return "GitHubの利用制限中です（HTTP 429）。しばらく待って再試行してください"
        default:
            return "GitHubがエラーを返しました（HTTP \(status)）。本文は表示しません"
        }
    }
}
