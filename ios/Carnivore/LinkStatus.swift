import Foundation
import Security

enum LinkStatus: Equatable, Sendable {
    case up, down, signedOut, unknown

    static func parse(statusCode: Int, body: Data) -> LinkStatus {
        guard statusCode == 200,
              let object = try? JSONSerialization.jsonObject(with: body) as? [String: Any],
              let word = object["status"] as? String else { return .unknown }
        switch word {
        case "up": return .up
        case "down": return .down
        case "signed_out": return .signedOut
        default: return .unknown
        }
    }
}

extension UnreachableReason {
    func refined(by status: LinkStatus) -> UnreachableReason {
        self == .linkOffline && status == .signedOut ? .signedOut : self
    }
}

enum StatusKeyStore {
    private static let service = "ai.carnivore.linkstatus"

    static func isWellFormed(_ token: String) -> Bool {
        token.range(of: "\\A[A-Za-z0-9_-]{22,128}\\z", options: .regularExpression) != nil
    }

    private static func query(origin: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service, kSecAttrAccount as String: origin]
    }

    @discardableResult
    static func set(_ token: String, origin: String) -> Bool {
        guard isWellFormed(token) else { return false }
        let data = Data(token.utf8)
        var status = SecItemUpdate(query(origin: origin) as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if status == errSecItemNotFound {
            var q = query(origin: origin)
            q[kSecValueData as String] = data
            q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            status = SecItemAdd(q as CFDictionary, nil)
        }
        return status == errSecSuccess
    }

    static func token(origin: String) -> String? {
        var q = query(origin: origin)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess, let data = out as? Data,
              let token = String(data: data, encoding: .utf8), isWellFormed(token) else { return nil }
        return token
    }

    static func remove(origin: String) {
        SecItemDelete(query(origin: origin) as CFDictionary)
    }
}

enum LinkStatusClient {
    static let base = URL(string: "https://api.carnivore.ai")!

    static func deviceId(of origin: Origin) -> String? {
        let suffix = ".link.carnivore.ai"
        guard origin.host.hasSuffix(suffix) else { return nil }
        let id = String(origin.host.dropLast(suffix.count))
        return id.range(of: "\\A[a-z2-7]{26}\\z", options: .regularExpression) != nil ? id : nil
    }

    static func request(deviceId: String, token: String) -> URLRequest {
        var r = URLRequest(url: base.appendingPathComponent("v1/relay/link-status/\(deviceId)"), timeoutInterval: 8)
        r.setValue(token, forHTTPHeaderField: "x-link-status-token")
        r.cachePolicy = .reloadIgnoringLocalCacheData
        return r
    }

    static func fetch(origin: Origin, session: URLSession = SecureSession.shared) async -> LinkStatus {
        guard let id = deviceId(of: origin), let token = StatusKeyStore.token(origin: origin.pushId),
              let (body, response) = try? await session.data(for: request(deviceId: id, token: token)),
              let http = response as? HTTPURLResponse else { return .unknown }
        return LinkStatus.parse(statusCode: http.statusCode, body: body)
    }
}
