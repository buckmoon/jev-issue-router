import Foundation

/// Calls the selected evaluator (Jev or Clef on Workers AI). Mirrors `issue_router/evaluators.py:Evaluator.call`:
/// no redirects are followed and response bodies are never surfaced, so issue text and credentials cannot leak
/// through an error. Workers AI's envelope is unwrapped before the engine validates the answers.
struct SystemOneClient {
    var evaluator: Evaluator
    var token: String
    var session: URLSession = .shared

    init(evaluator: Evaluator, token: String, session: URLSession = .shared) {
        self.evaluator = evaluator
        self.token = token
        self.session = session
    }

    func evaluate(_ request: JSONValue) async throws -> JSONValue {
        let label = evaluator.label
        var urlRequest = URLRequest(url: try evaluator.url(for: request["model"]?.stringValue),
                                    timeoutInterval: evaluator.timeout)
        urlRequest.httpMethod = "POST"
        urlRequest.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.httpBody = Data(request.serialized().utf8)
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: urlRequest, delegate: NoRedirect())
        } catch {
            throw RouterError("\(label) network/timeout/JSON error; no recommendation generated")
        }
        if let http = response as? HTTPURLResponse, !(200...299).contains(http.statusCode) {
            throw RouterError("\(label) HTTP \(http.statusCode); response body omitted to protect input and credentials")
        }
        guard let value = try? JSONValue.decode(data), value.isObject else {
            throw RouterError("\(label) network/timeout/JSON error; no recommendation generated")
        }
        return evaluator.envelope ? try Self.unwrapWorkersAI(value, label: label) : value
    }

    /// Workers AI REST wraps the System One response: {"result": {...}, "success": bool, "errors": [...]}.
    /// Only numeric error codes are surfaced; messages could echo input.
    static func unwrapWorkersAI(_ payload: JSONValue, label: String) throws -> JSONValue {
        if case .bool(true) = payload["success"] ?? .null, let result = payload["result"], result.isObject {
            return result
        }
        let codes = Set((payload["errors"]?.arrayValue ?? []).compactMap { error -> Int? in
            if case let .int(code) = error["code"] ?? .null { return code }
            return nil
        }).sorted()
        let list = "[" + codes.map(String.init).joined(separator: ", ") + "]"
        throw RouterError("\(label) request failed (Cloudflare error codes \(list)); response body omitted")
    }

    /// One tiny fixed question per distinct model proves the evaluator answers; no user input is sent.
    func check() async throws -> (models: [String], checkedAt: String) {
        var models: [String] = []
        for model in evaluator.distinctModels {
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
                throw RouterError(checkFailure(error.message))
            }
            guard response["answers"]?.isObject == true else {
                throw RouterError("NG — \(evaluator.label) APIの応答形式が想定と異なります")
            }
            models.append(String((response["model"]?.stringValue ?? model).prefix(60)))
        }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "HH:mm"
        return (models: models, checkedAt: formatter.string(from: Date()))
    }

    /// Same wording as `issue_router/app.py:check_connection`.
    private func checkFailure(_ message: String) -> String {
        let label = evaluator.label
        let head = message.split(separator: ";").first.map(String.init) ?? message
        if message.contains("HTTP 401") || message.contains("HTTP 403") {
            let hint = evaluator.host == "workers-ai" ? "トークンの値、Workers AI権限、アカウントIDを確認してください"
                : "キーとAPI利用権限を確認してください"
            return "NG — キーが拒否されました（\(head)）。" + hint
        }
        if message.contains("HTTP 429") {
            return "NG — キーは届きましたが利用制限中です（\(label) HTTP 429）。残高・制限を確認してください"
        }
        if message.contains("HTTP") {
            return "NG — \(label) APIがエラーを返しました（\(head)）"
        }
        if message.contains("network") {
            return "NG — \(label) APIに接続できません。ネットワークを確認してください"
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
