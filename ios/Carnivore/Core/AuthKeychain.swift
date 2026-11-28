import Foundation
import Security

struct AuthCredentials: Codable, Equatable, Sendable {
    var accessToken: String
    var refreshToken: String
    var linkCookie: String?
    var expiresAt: Date?

    var hasTokens: Bool {
        !accessToken.isEmpty
    }

    var isExpiringSoon: Bool {
        guard let expiresAt else { return false }
        return expiresAt.timeIntervalSinceNow < 90
    }
}

enum AuthKeychain {
    private static let service = "ai.carnivore.auth.v1"

    private static func query(origin: String) -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: origin,
        ]
    }

    @discardableResult
    static func save(_ creds: AuthCredentials, origin: String) -> Bool {
        guard let data = try? JSONEncoder().encode(creds) else { return false }
        let update = [kSecValueData as String: data] as CFDictionary
        var status = SecItemUpdate(query(origin: origin) as CFDictionary, update)
        if status == errSecItemNotFound {
            var q = query(origin: origin)
            q[kSecValueData as String] = data
            q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            status = SecItemAdd(q as CFDictionary, nil)
        }
        return status == errSecSuccess
    }

    @discardableResult
    static func saveLinkCookie(_ cookieHeader: String, origin: String) -> Bool {
        var existing = load(origin: origin) ?? AuthCredentials(accessToken: "", refreshToken: "", linkCookie: nil, expiresAt: nil)
        existing.linkCookie = cookieHeader
        return save(existing, origin: origin)
    }

    static func clearTokensPreservingLinkCookie(origin: String) {
        if let existing = load(origin: origin), let cookie = existing.linkCookie, !cookie.isEmpty {
            _ = save(AuthCredentials(accessToken: "", refreshToken: "", linkCookie: cookie, expiresAt: nil), origin: origin)
        } else {
            remove(origin: origin)
        }
    }

    static func load(origin: String) -> AuthCredentials? {
        var q = query(origin: origin)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess,
              let data = out as? Data,
              let creds = try? JSONDecoder().decode(AuthCredentials.self, from: data) else {
            return nil
        }
        return creds
    }

    static func remove(origin: String) {
        SecItemDelete(query(origin: origin) as CFDictionary)
    }

    static func removeAll() {
        let q: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
        ]
        SecItemDelete(q as CFDictionary)
    }
}
