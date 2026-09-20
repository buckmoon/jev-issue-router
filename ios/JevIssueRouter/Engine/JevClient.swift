import Foundation

/// Calls the TypeSafe Jev API. Mirrors `issue_router/core.py:evaluate`: no redirects are followed and
/// response bodies are never surfaced, so issue text and credentials cannot leak through an error.
struct JevClient {
    static let endpoint = URL(string: "https://api.typesafe.ai/v1/systemone")!
    static let defaultModel = "jev-latest"

    var apiKey: String
    var session: URLSession = .shared

    func evaluate(_ request: JSONValue) async throws -> JSONValue {
        var urlRequest = URLRequest(url: Self.endpoint, timeoutInterval: 60)
        urlRequest.httpMethod = "POST"
        urlRequest.setValue("Bearer " + apiKey, forHTTPHeaderField: "Authorization")
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.httpBody = Data(request.serialized().utf8)
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: urlRequest, delegate: NoRedirect())
        } catch {
            throw RouterError("Jev network/timeout/JSON error; no recommendation generated")
        }
        if let http = response as? HTTPURLResponse, !(200...299).contains(http.statusCode) {
            throw RouterError("Jev HTTP \(http.statusCode); response body omitted to protect input and credentials")
        }
        guard let value = try? JSONValue.decode(data), value.isObject else {
            throw RouterError("Jev network/timeout/JSON error; no recommendation generated")
        }
        return value
    }

    /// One tiny fixed question proves the key is accepted; no user input is sent.
    func check(model: String = defaultModel) async throws -> (model: String, checkedAt: String) {
        let request = JSONValue.fields([
            ("model", .string(model)),
            ("state", .strings([("text", "ping")])),
            ("questions", .fields([
                ("ok", .fields([
                    ("type", .string("choice")),
                    ("instructions", .string("Select yes.")),
                    ("criteria", .strings([("yes", "Always select this."), ("no", "Never select this.")])),
                ])),
            ])),
        ])
        let response: JSONValue
        do {
            response = try await evaluate(request)
        } catch let error as RouterError {
            throw RouterError(Self.checkFailure(error.message))
        }
        guard response["answers"]?.isObject == true else {
            throw RouterError("NG — Jev APIの応答形式が想定と異なります")
        }
        let name = String((response["model"]?.stringValue ?? "jev").prefix(60))
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "HH:mm"
        return (model: name, checkedAt: formatter.string(from: Date()))
    }

    private static func checkFailure(_ message: String) -> String {
        let head = message.split(separator: ";").first.map(String.init) ?? message
        if message.contains("HTTP 401") || message.contains("HTTP 403") {
            return "NG — キーが拒否されました（\(head)）。キーとAPI利用権限を確認してください"
        }
        if message.contains("HTTP 429") {
            return "NG — キーは届きましたが利用制限中です（Jev HTTP 429）。残高・制限を確認してください"
        }
        if message.contains("HTTP") {
            return "NG — Jev APIがエラーを返しました（\(head)）"
        }
        if message.contains("network") {
            return "NG — Jev APIに接続できません。ネットワークを確認してください"
        }
        return "NG — " + message
    }
}

/// Refuses redirects so a moved endpoint cannot forward the Authorization header elsewhere.
final class NoRedirect: NSObject, URLSessionTaskDelegate {
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}
