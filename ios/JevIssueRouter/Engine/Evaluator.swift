import Foundation

/// Port of `issue_router/evaluators.py`. The decision model that judges the issue: Jev on TypeSafe, or Clef
/// on Cloudflare Workers AI. Both take the same System One request; only URL, credentials, model name and
/// the response envelope differ. The local Clef host is not offered on iOS: a device cannot reach the Mac's
/// loopback, and plain http on a LAN would break the TLS-or-loopback rule.
struct Evaluator: Equatable {
    static let names = ["jev", "clef"]
    static let hosts = ["typesafe", "workers-ai"]  // a subset of the Python hosts
    static let stages = ["assess", "select"]  // first call: assessment; second call: selection
    static let labels = ["jev": "Jev", "clef": "Clef"]
    static let jevURL = "https://api.typesafe.ai/v1/systemone"
    static let workersAIURL = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/@cf/cloudflare/{model}"
    static let workersAIModels = ["clef", "clef-flash"]
    static let clefContextTokens = 65536  // Clef truncates long state silently; see contextTokens
    static let timeouts = ["typesafe": 60, "workers-ai": 60]
    static let keychainServices = ["jev": "local.jev.typesafe", "clef": "local.clef.cloudflare"]
    static let defaultJevModel = "jev-latest"

    let name: String
    let host: String
    let assessModel: String
    let selectModel: String
    /// Workers AI keeps a {model} placeholder that is filled per request; Jev is a fixed URL.
    let urlTemplate: String
    let timeout: TimeInterval
    /// Workers AI wraps the System One response in {"result": ..., "success": ...}.
    let envelope: Bool
    /// Warn when usage.input_tokens approaches this.
    let contextTokens: Int?

    var label: String { Self.labels[name] ?? "Jev" }
    var keychainService: String { Self.keychainServices[name] ?? Self.keychainServices["jev"]! }
    /// Each distinct model once, assessment stage first.
    var distinctModels: [String] { assessModel == selectModel ? [selectModel] : [assessModel, selectModel] }

    static func jev(model: String = defaultJevModel) -> Evaluator {
        Evaluator(name: "jev", host: "typesafe", assessModel: model, selectModel: model, urlTemplate: jevURL,
                  timeout: TimeInterval(timeouts["typesafe"]!), envelope: false, contextTokens: nil)
    }

    /// Mirrors make_evaluator("clef", clef_host="workers-ai"): the assessment model defaults to the selection model.
    static func workersAI(accountID: String, model: String = "clef", assessModel: String? = nil) throws -> Evaluator {
        let assess = assessModel.flatMap { $0.isEmpty ? nil : $0 } ?? model
        guard workersAIModels.contains(model), workersAIModels.contains(assess) else {
            throw RouterError("Workers AIのClefモデルは clef か clef-flash です")
        }
        guard accountID.range(of: "^[0-9a-f]{32}$", options: .regularExpression) != nil else {
            throw RouterError("CloudflareアカウントIDは32桁の16進数（小文字）で入力してください")
        }
        let template = workersAIURL.replacingOccurrences(of: "{account}", with: accountID)
        return Evaluator(name: "clef", host: "workers-ai", assessModel: assess, selectModel: model,
                         urlTemplate: template, timeout: TimeInterval(timeouts["workers-ai"]!), envelope: true,
                         contextTokens: clefContextTokens)
    }

    /// Goes into the result JSON; never the URL, the account ID or secrets.
    func describe() -> JSONValue {
        .fields([("name", .string(name)), ("host", .string(host)),
                 ("models", .strings([("assess", assessModel), ("select", selectModel)]))])
    }

    /// Only the configured, validated model names reach the URL.
    func url(for model: String?) throws -> URL {
        guard let model, model == assessModel || model == selectModel,
              let url = URL(string: urlTemplate.replacingOccurrences(of: "{model}", with: model)) else {
            throw RouterError("Request model is not one of the configured evaluator models")
        }
        return url
    }
}
