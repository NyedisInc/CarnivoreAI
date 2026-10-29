import CryptoKit
import Foundation
import Security

enum PushKeyStore {
    private static let service = "ai.carnivore.push"
    private static let account = "payload-keys"

    private static var accessGroup: String? {
        let value = Bundle.main.object(forInfoDictionaryKey: "CarnivoreKeychainGroup") as? String
        return (value?.isEmpty == false && value?.contains("$(") == false) ? value : nil
    }

    static let accessibility = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly

    private static let registeredKey = "push.registered.v1"
    private static var defaults: UserDefaults { UserDefaults(suiteName: "group.ai.carnivore") ?? .standard }

    private static func query() -> [String: Any] {
        var q: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
                                kSecAttrService as String: service, kSecAttrAccount as String: account]
        if let group = accessGroup { q[kSecAttrAccessGroup as String] = group }
        return q
    }

    struct Entry: Codable, Equatable {
        let origin: String
        var key: Data
        var rowId: String?
    }

    static func entries() -> [Entry] {
        var q = query()
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let data = out as? Data,
              let list = try? JSONDecoder().decode([Entry].self, from: data) else { return [] }
        return list.filter { $0.key.count == 32 }
    }

    @discardableResult
    private static func save(_ list: [Entry]) -> Bool {
        guard !list.isEmpty else {
            let status = SecItemDelete(query() as CFDictionary)
            return status == errSecSuccess || status == errSecItemNotFound
        }
        guard let data = try? JSONEncoder().encode(list) else { return false }
        let update = [kSecValueData as String: data] as CFDictionary
        var status = SecItemUpdate(query() as CFDictionary, update)
        if status == errSecItemNotFound {
            var q = query()
            q[kSecValueData as String] = data
            q[kSecAttrAccessible as String] = accessibility
            status = SecItemAdd(q as CFDictionary, nil)
        }
        return status == errSecSuccess
    }

    static func preparing(_ list: [Entry], origin: String) -> (list: [Entry], key: SymmetricKey) {
        var out = list
        if let i = out.firstIndex(where: { $0.origin == origin }), out[i].rowId == nil {
            return (out, SymmetricKey(data: out[i].key))
        }
        let fresh = SymmetricKey(size: .bits256)
        let entry = Entry(origin: origin, key: fresh.withUnsafeBytes { Data($0) }, rowId: nil)
        if let i = out.firstIndex(where: { $0.origin == origin }) { out[i] = entry } else { out.append(entry) }
        return (out, fresh)
    }

    static func setting(rowId id: String, origin: String, in list: [Entry]) -> [Entry] {
        var out = list
        guard isRowId(id), let i = out.firstIndex(where: { $0.origin == origin }) else { return out }
        out[i].rowId = id
        return out
    }

    static func keyForRegistration(origin: String) -> SymmetricKey? {
        let prepared = preparing(entries(), origin: origin)
        return save(prepared.list) ? prepared.key : nil
    }

    static func setRowId(_ id: String, origin: String) {
        let list = entries()
        let updated = setting(rowId: id, origin: origin, in: list)
        if updated != list { save(updated) }
        if updated.contains(where: { $0.origin == origin && $0.rowId == id }) {
            defaults.set(Array(Set(registeredOrigins()).union([origin])), forKey: registeredKey)
        }
    }

    static func registeredOrigins() -> [String] {
        defaults.stringArray(forKey: registeredKey) ?? []
    }

    static func needsReregistration(origin: String, registered: [String], entries list: [Entry]) -> Bool {
        registered.contains(origin) && !list.contains { $0.origin == origin }
    }

    static func needsReregistration(origin: String) -> Bool {
        needsReregistration(origin: origin, registered: registeredOrigins(), entries: entries())
    }

    static func migrateAccessibility() {
        let update = [kSecAttrAccessible as String: accessibility] as CFDictionary
        let status = SecItemUpdate(query() as CFDictionary, update)
        if status != errSecSuccess && status != errSecItemNotFound {
            NSLog("carnivore: push key migration failed: \(status)")
        }
    }

    static func remove(origin: String) {
        let list = entries()
        let kept = list.filter { $0.origin != origin }
        defaults.set(registeredOrigins().filter { $0 != origin }, forKey: registeredKey)
        if kept.count != list.count { save(kept) }
    }

    static func candidates() -> [PushRewrite.Candidate] {
        candidates(from: entries())
    }

    static func candidates(from list: [Entry]) -> [PushRewrite.Candidate] {
        list.compactMap { e in
            e.rowId.map { PushRewrite.Candidate(origin: e.origin, key: SymmetricKey(data: e.key), rowId: $0) }
        }
    }

    static func base64url(_ key: SymmetricKey) -> String {
        key.withUnsafeBytes { Data($0) }.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    static func isRowId(_ value: String) -> Bool {
        value.range(of: "^d_[0-9a-f]{12}$", options: .regularExpression) != nil
    }
}
