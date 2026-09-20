import Foundation
import Security

/// Secrets live only in the iOS Keychain: device-only, never synced to iCloud, never written to a file,
/// never logged. Saved values are not readable from the UI; only presence and save time are shown.
enum Keychain {
    /// Same service name as the CLI and the macOS app use for the TypeSafe key.
    static let typesafeService = "local.jev.typesafe"
    static let githubService = "local.jev.github"
    static let account = "jev-issue-router"

    struct Entry {
        let exists: Bool
        let savedAt: Date?
    }

    static func save(_ secret: String, service: String) throws {
        let value = secret.trimmingCharacters(in: .whitespacesAndNewlines)
        guard (8...4096).contains(value.count),
              value.unicodeScalars.allSatisfy({ (0x21...0x7e).contains($0.value) }) else {
            throw RouterError("キーの形式が正しくありません")
        }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        let attributes: [String: Any] = [
            kSecValueData as String: Data(value.utf8),
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
        ]
        let updated = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if updated == errSecItemNotFound {
            let status = SecItemAdd(query.merging(attributes) { current, _ in current } as CFDictionary, nil)
            guard status == errSecSuccess else { throw RouterError("Keychainへの保存に失敗しました") }
            return
        }
        guard updated == errSecSuccess else { throw RouterError("Keychainへの保存に失敗しました") }
    }

    static func read(service: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let data = item as? Data, let value = String(data: data, encoding: .utf8) else {
            return nil
        }
        return value
    }

    /// Reads attributes only, never the secret itself.
    static func entry(service: String) -> Entry {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
            kSecReturnAttributes as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let attributes = item as? [String: Any] else {
            return Entry(exists: false, savedAt: nil)
        }
        return Entry(exists: true, savedAt: attributes[kSecAttrModificationDate as String] as? Date)
    }

    static func delete(service: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        SecItemDelete(query as CFDictionary)
    }
}
