import Foundation

/// Runs the Swift engine against Python-generated fake responses. Never uses a network client.
@main
struct IOSParity {
    static func main() async throws {
        let input = try JSONValue.decode(Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1])))
        let catalog = try Catalog(input["catalog"]!)
        let responses = input["responses"]!.arrayValue!
        let rawIssue = input["issue"]!
        let issue = try Router.normalizeIssue(title: rawIssue["title"]?.stringValue ?? "",
            body: rawIssue["body"]?.stringValue ?? "", context: rawIssue["context"]?.stringValue ?? "")
        var index = 0
        var requests: [JSONValue] = []
        let result = try await Router.route(issue: issue, catalog: catalog,
            policy: input["policy"]!.stringValue!, evaluate: { request in
                requests.append(request)
                defer { index += 1 }
                return responses[index]
            })
        print(JSONValue.fields([("result", result), ("requests", .array(requests)),
            ("render", .string(Render.text(result)))]).serialized())
    }
}
