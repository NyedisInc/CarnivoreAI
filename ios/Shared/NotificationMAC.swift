import CryptoKit
import Foundation
import Security

enum NotificationMAC {
    static let macKey = "_mac"
    private static let service = "ai.carnivore.notify.mac"
    private static let account = "userinfo-hmac-v1"
    private static let signedFields = ["kind", "cap", "base", "ttl", "card", "acts", "media", "settle", "path", "origin", "thread"]

    private static var accessGroup: String? {
        let value = Bundle.main.object(forInfoDictionaryKey: "CarnivoreMacKeychainGroup") as? String
        return (value?.isEmpty == false && value?.contains("$(") == false) ? value : nil
    }

    private static func query() -> [String: Any] {
        var q: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
        if let group = accessGroup { q[kSecAttrAccessGroup as String] = group }
        return q
    }

    static func deviceKey() -> SymmetricKey? {
        var q = query()
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: AnyObject?
        if SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let data = out as? Data, data.count == 32 {
            return SymmetricKey(data: data)
        }
        let fresh = SymmetricKey(size: .bits256)
        let bytes = fresh.withUnsafeBytes { Data($0) }
        var add = query()
        add[kSecValueData as String] = bytes
        add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = SecItemAdd(add as CFDictionary, nil)
        if status == errSecDuplicateItem {
            if SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let data = out as? Data, data.count == 32 {
                return SymmetricKey(data: data)
            }
        }
        return status == errSecSuccess ? fresh : nil
    }

    static func canonicalPayload(for userInfo: [AnyHashable: Any]) -> Data {
        var data = Data("carnivore-notify-mac-v1\0".utf8)
        for field in signedFields {
            data.append(contentsOf: field.utf8)
            data.append(0x3D)
            if let value = userInfo[field] as? String {
                let utf8 = Data(value.utf8)
                var len = UInt32(utf8.count).bigEndian
                withUnsafeBytes(of: &len) { data.append(contentsOf: $0) }
                data.append(utf8)
            } else {
                var absent = UInt32.max.bigEndian
                withUnsafeBytes(of: &absent) { data.append(contentsOf: $0) }
            }
            data.append(0x0A)
        }
        return data
    }

    static func compute(for userInfo: [AnyHashable: Any], key: SymmetricKey) -> String {
        let mac = HMAC<SHA256>.authenticationCode(for: canonicalPayload(for: userInfo), using: key)
        return Data(mac).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }

    static func sign(_ userInfo: [String: String], key: SymmetricKey? = deviceKey()) -> [String: String] {
        guard let key else { return userInfo }
        var signed = userInfo
        signed[macKey] = compute(for: signed, key: key)
        return signed
    }

    static func verify(_ userInfo: [AnyHashable: Any], key: SymmetricKey? = deviceKey()) -> Bool {
        guard let key, let expected = userInfo[macKey] as? String, !expected.isEmpty else { return false }
        let actual = compute(for: userInfo, key: key)
        return constantTimeEqual(Data(expected.utf8), Data(actual.utf8))
    }

    private static func constantTimeEqual(_ a: Data, _ b: Data) -> Bool {
        guard a.count == b.count else { return false }
        var diff: UInt8 = 0
        for (x, y) in zip(a, b) { diff |= (x ^ y) }
        return diff == 0
    }
}
