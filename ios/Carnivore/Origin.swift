import Foundation

struct Origin: Equatable, Codable, Hashable {
    let scheme: String
    let host: String
    let port: Int

    init?(url: URL) {
        guard let scheme = url.scheme?.lowercased(), scheme == "http" || scheme == "https",
              let host = url.host?.lowercased(), !host.isEmpty else { return nil }
        self.scheme = scheme
        self.host = host
        self.port = url.port ?? (scheme == "https" ? 443 : 80)
    }

    var rootURL: URL {
        let defaultPort = scheme == "https" ? 443 : 80
        var c = URLComponents()
        c.scheme = scheme
        c.host = host
        if port != defaultPort { c.port = port }
        c.path = "/"
        return c.url!
    }

    var isEncrypted: Bool { scheme == "https" }

    var pushId: String { "\(scheme)://\(host):\(port)" }
}

enum NavigationDecision: Equatable {
    case allow
    case openInSafari
    case block
}

enum OriginLock {
    static func decide(_ url: URL, lockedTo origin: Origin) -> NavigationDecision {
        let scheme = url.scheme?.lowercased()
        if scheme == "about", url.absoluteString == "about:blank" { return .allow }
        guard let target = Origin(url: url) else { return .block }
        return target == origin ? .allow : .openInSafari
    }
}
