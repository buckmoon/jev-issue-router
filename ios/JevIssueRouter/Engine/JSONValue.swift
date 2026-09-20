import Foundation

/// JSON tree that keeps object key order, so requests and results match the Python engine byte for byte.
/// `Foundation.JSONSerialization` sorts or randomises keys, which would change the input hash.
enum JSONValue {
    case null
    case bool(Bool)
    case int(Int)
    case double(Double)
    case string(String)
    case array([JSONValue])
    case object([(key: String, value: JSONValue)])

    /// Builds an object from plain pairs. Named differently from the `object` case on purpose:
    /// an overload sharing the case name makes some Swift compilation modes report a circular reference.
    static func fields(_ pairs: [(String, JSONValue)]) -> JSONValue {
        .object(pairs.map { (key: $0.0, value: $0.1) })
    }

    static func strings(_ pairs: [(String, String)]) -> JSONValue {
        .object(pairs.map { (key: $0.0, value: JSONValue.string($0.1)) })
    }
}

// MARK: - Reading

extension JSONValue {
    subscript(key: String) -> JSONValue? {
        guard case let .object(pairs) = self else { return nil }
        return pairs.first { $0.key == key }?.value
    }

    var stringValue: String? {
        if case let .string(value) = self { return value }
        return nil
    }

    var doubleValue: Double? {
        switch self {
        case let .double(value): return value
        case let .int(value): return Double(value)
        default: return nil
        }
    }

    var arrayValue: [JSONValue]? {
        if case let .array(values) = self { return values }
        return nil
    }

    var objectValue: [(key: String, value: JSONValue)]? {
        if case let .object(pairs) = self { return pairs }
        return nil
    }

    var isObject: Bool { objectValue != nil }
}

// MARK: - Writing

extension JSONValue {
    /// `ensureASCII` and the default separators reproduce Python's `json.dumps`, which the input hash depends on.
    func serialized(indent: Int? = nil, ensureASCII: Bool = true, sortKeys: Bool = false) -> String {
        var out = ""
        write(to: &out, indent: indent, ensureASCII: ensureASCII, sortKeys: sortKeys, depth: 0)
        return out
    }

    private func write(to out: inout String, indent: Int?, ensureASCII: Bool, sortKeys: Bool, depth: Int) {
        let pad = indent.map { String(repeating: " ", count: $0 * (depth + 1)) } ?? ""
        let closePad = indent.map { String(repeating: " ", count: $0 * depth) } ?? ""
        let newline = indent == nil ? "" : "\n"
        let comma = indent == nil ? ", " : ","
        let colon = indent == nil ? ": " : ": "
        switch self {
        case .null:
            out += "null"
        case let .bool(value):
            out += value ? "true" : "false"
        case let .int(value):
            out += String(value)
        case let .double(value):
            out += value.isFinite ? String(value) : "null"
        case let .string(value):
            out += JSONValue.quote(value, ensureASCII: ensureASCII)
        case let .array(values):
            if values.isEmpty { out += "[]"; return }
            out += "[" + newline
            for (index, value) in values.enumerated() {
                out += pad
                value.write(to: &out, indent: indent, ensureASCII: ensureASCII, sortKeys: sortKeys, depth: depth + 1)
                if index < values.count - 1 { out += comma + newline }
            }
            out += newline + closePad + "]"
        case let .object(pairs):
            if pairs.isEmpty { out += "{}"; return }
            let items = sortKeys ? pairs.sorted { $0.key < $1.key } : pairs
            out += "{" + newline
            for (index, item) in items.enumerated() {
                out += pad + JSONValue.quote(item.key, ensureASCII: ensureASCII) + colon
                item.value.write(to: &out, indent: indent, ensureASCII: ensureASCII, sortKeys: sortKeys, depth: depth + 1)
                if index < items.count - 1 { out += comma + newline }
            }
            out += newline + closePad + "}"
        }
    }

    private static func quote(_ text: String, ensureASCII: Bool) -> String {
        var out = "\""
        for scalar in text.unicodeScalars {
            switch scalar {
            case "\"": out += "\\\""
            case "\\": out += "\\\\"
            case "\n": out += "\\n"
            case "\r": out += "\\r"
            case "\t": out += "\\t"
            case "\u{08}": out += "\\b"
            case "\u{0C}": out += "\\f"
            default:
                if scalar.value < 0x20 || (ensureASCII && scalar.value > 0x7e) {
                    if scalar.value > 0xFFFF {
                        // Python escapes astral characters as a UTF-16 surrogate pair.
                        let value = scalar.value - 0x10000
                        out += String(format: "\\u%04x\\u%04x", 0xD800 + (value >> 10), 0xDC00 + (value & 0x3FF))
                    } else {
                        out += String(format: "\\u%04x", scalar.value)
                    }
                } else {
                    out.unicodeScalars.append(scalar)
                }
            }
        }
        return out + "\""
    }
}

// MARK: - Parsing

extension JSONValue {
    /// Hand-written parser because `JSONDecoder` loses object key order, and the engine echoes Jev's
    /// answers back to Jev and ranks equal probabilities in the order they arrived.
    static func decode(_ data: Data) throws -> JSONValue {
        var parser = JSONParser(bytes: [UInt8](data))
        let value = try parser.parseValue()
        parser.skipWhitespace()
        guard parser.atEnd else { throw RouterError("Invalid JSON") }
        return value
    }
}

private struct JSONParser {
    let bytes: [UInt8]
    var index = 0

    var atEnd: Bool { index >= bytes.count }

    mutating func skipWhitespace() {
        while index < bytes.count, bytes[index] == 0x20 || bytes[index] == 0x09
                || bytes[index] == 0x0A || bytes[index] == 0x0D {
            index += 1
        }
    }

    mutating func parseValue() throws -> JSONValue {
        skipWhitespace()
        guard index < bytes.count else { throw RouterError("Invalid JSON") }
        switch bytes[index] {
        case UInt8(ascii: "{"): return try parseObject()
        case UInt8(ascii: "["): return try parseArray()
        case UInt8(ascii: "\""): return .string(try parseString())
        case UInt8(ascii: "t"): try expect("true"); return .bool(true)
        case UInt8(ascii: "f"): try expect("false"); return .bool(false)
        case UInt8(ascii: "n"): try expect("null"); return .null
        default: return try parseNumber()
        }
    }

    private mutating func expect(_ literal: String) throws {
        let expected = [UInt8](literal.utf8)
        guard index + expected.count <= bytes.count,
              Array(bytes[index..<(index + expected.count)]) == expected else {
            throw RouterError("Invalid JSON")
        }
        index += expected.count
    }

    private mutating func parseObject() throws -> JSONValue {
        index += 1  // {
        var pairs: [(key: String, value: JSONValue)] = []
        skipWhitespace()
        if index < bytes.count, bytes[index] == UInt8(ascii: "}") {
            index += 1
            return .object(pairs)
        }
        while true {
            skipWhitespace()
            guard index < bytes.count, bytes[index] == UInt8(ascii: "\"") else { throw RouterError("Invalid JSON") }
            let key = try parseString()
            skipWhitespace()
            guard index < bytes.count, bytes[index] == UInt8(ascii: ":") else { throw RouterError("Invalid JSON") }
            index += 1
            let value = try parseValue()
            // Like Python's json, a repeated key keeps its first position and the last value.
            if let existing = pairs.firstIndex(where: { $0.key == key }) {
                pairs[existing].value = value
            } else {
                pairs.append((key: key, value: value))
            }
            skipWhitespace()
            guard index < bytes.count else { throw RouterError("Invalid JSON") }
            if bytes[index] == UInt8(ascii: ",") { index += 1; continue }
            if bytes[index] == UInt8(ascii: "}") { index += 1; return .object(pairs) }
            throw RouterError("Invalid JSON")
        }
    }

    private mutating func parseArray() throws -> JSONValue {
        index += 1  // [
        var values: [JSONValue] = []
        skipWhitespace()
        if index < bytes.count, bytes[index] == UInt8(ascii: "]") {
            index += 1
            return .array(values)
        }
        while true {
            values.append(try parseValue())
            skipWhitespace()
            guard index < bytes.count else { throw RouterError("Invalid JSON") }
            if bytes[index] == UInt8(ascii: ",") { index += 1; continue }
            if bytes[index] == UInt8(ascii: "]") { index += 1; return .array(values) }
            throw RouterError("Invalid JSON")
        }
    }

    private mutating func parseString() throws -> String {
        index += 1  // opening quote
        var scalars = String.UnicodeScalarView()
        var raw = [UInt8]()

        func flushRaw() throws {
            guard !raw.isEmpty else { return }
            guard let text = String(bytes: raw, encoding: .utf8) else { throw RouterError("Invalid JSON") }
            scalars.append(contentsOf: text.unicodeScalars)
            raw.removeAll(keepingCapacity: true)
        }

        while index < bytes.count {
            let byte = bytes[index]
            if byte == UInt8(ascii: "\"") {
                index += 1
                try flushRaw()
                return String(scalars)
            }
            if byte == UInt8(ascii: "\\") {
                try flushRaw()
                index += 1
                guard index < bytes.count else { throw RouterError("Invalid JSON") }
                let escape = bytes[index]
                index += 1
                switch escape {
                case UInt8(ascii: "\""): scalars.append("\"")
                case UInt8(ascii: "\\"): scalars.append("\\")
                case UInt8(ascii: "/"): scalars.append("/")
                case UInt8(ascii: "b"): scalars.append("\u{08}")
                case UInt8(ascii: "f"): scalars.append("\u{0C}")
                case UInt8(ascii: "n"): scalars.append("\n")
                case UInt8(ascii: "r"): scalars.append("\r")
                case UInt8(ascii: "t"): scalars.append("\t")
                case UInt8(ascii: "u"):
                    let first = try parseHex4()
                    if first >= 0xD800, first <= 0xDBFF, index + 1 < bytes.count,
                       bytes[index] == UInt8(ascii: "\\"), bytes[index + 1] == UInt8(ascii: "u") {
                        index += 2
                        let second = try parseHex4()
                        guard second >= 0xDC00, second <= 0xDFFF else { throw RouterError("Invalid JSON") }
                        let combined = 0x10000 + ((first - 0xD800) << 10) + (second - 0xDC00)
                        guard let scalar = Unicode.Scalar(combined) else { throw RouterError("Invalid JSON") }
                        scalars.append(scalar)
                    } else {
                        guard let scalar = Unicode.Scalar(first) else { throw RouterError("Invalid JSON") }
                        scalars.append(scalar)
                    }
                default:
                    throw RouterError("Invalid JSON")
                }
                continue
            }
            raw.append(byte)
            index += 1
        }
        throw RouterError("Invalid JSON")
    }

    private mutating func parseHex4() throws -> UInt32 {
        guard index + 4 <= bytes.count,
              let text = String(bytes: bytes[index..<(index + 4)], encoding: .utf8),
              let value = UInt32(text, radix: 16) else {
            throw RouterError("Invalid JSON")
        }
        index += 4
        return value
    }

    private mutating func parseNumber() throws -> JSONValue {
        let start = index
        var isInteger = true
        if index < bytes.count, bytes[index] == UInt8(ascii: "-") { index += 1 }
        while index < bytes.count {
            let byte = bytes[index]
            if byte >= UInt8(ascii: "0"), byte <= UInt8(ascii: "9") {
                index += 1
            } else if byte == UInt8(ascii: ".") || byte == UInt8(ascii: "e") || byte == UInt8(ascii: "E")
                        || byte == UInt8(ascii: "+") || byte == UInt8(ascii: "-") {
                isInteger = false
                index += 1
            } else {
                break
            }
        }
        guard index > start, let text = String(bytes: bytes[start..<index], encoding: .utf8) else {
            throw RouterError("Invalid JSON")
        }
        if isInteger, let value = Int(text) { return .int(value) }
        guard let value = Double(text), value.isFinite else { throw RouterError("Invalid JSON") }
        return .double(value)
    }
}
