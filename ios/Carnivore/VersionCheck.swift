import Foundation

enum AppVersion {
    static let minServer = "1.14.0"

    static var marketing: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0"
    }
}

enum VersionStatus: Equatable {
    case compatible(server: String)
    case serverTooOld(server: String, needs: String)
    case unknown(reason: String)

    var warning: String? {
        switch self {
        case .compatible: return nil
        case .serverTooOld(let server, let needs):
            return Strings.fill(Strings.versionTooOld, ["server": server, "needs": needs])
        case .unknown(let reason): return Strings.fill(Strings.versionUnknown, ["reason": reason])
        }
    }
}

enum VersionCheck {
    static func isOlder(_ a: String, than b: String) -> Bool {
        let x = a.split(separator: ".").map { Int($0) ?? 0 }
        let y = b.split(separator: ".").map { Int($0) ?? 0 }
        for i in 0..<max(x.count, y.count) {
            let l = i < x.count ? x[i] : 0, r = i < y.count ? y[i] : 0
            if l != r { return l < r }
        }
        return false
    }

    static func status(serverVersion: String) -> VersionStatus {
        if serverVersion.isEmpty { return .unknown(reason: Strings.versionNoReport) }
        return isOlder(serverVersion, than: AppVersion.minServer)
            ? .serverTooOld(server: serverVersion, needs: AppVersion.minServer)
            : .compatible(server: serverVersion)
    }

    static func fetch(origin: Origin) async -> VersionStatus {
        let url = origin.rootURL.appendingPathComponent("api/v1/health")
        do {
            var request = URLRequest(url: url, timeoutInterval: 8)
            request.httpShouldHandleCookies = false
            let (data, response) = try await URLSession.shared.data(for: request)
            guard (response as? HTTPURLResponse)?.statusCode == 200,
                  let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                return .unknown(reason: Strings.versionUnexpected)
            }
            return status(serverVersion: obj["version"] as? String ?? "")
        } catch {
            return .unknown(reason: error.localizedDescription)
        }
    }
}
