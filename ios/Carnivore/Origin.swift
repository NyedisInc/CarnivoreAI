import Foundation

struct Origin: Equatable, Codable, Hashable, Sendable {
    let scheme: String
    let host: String
    let port: Int

    var isIPv6: Bool { host.contains(":") }

    var uriHost: String { isIPv6 ? "[\(host)]" : host }

    init?(url: URL) {
        guard let scheme = url.scheme?.lowercased(), scheme == "http" || scheme == "https",
              var rawHost = url.host?.lowercased(), !rawHost.isEmpty else { return nil }
        if rawHost.hasPrefix("["), rawHost.hasSuffix("]") {
            rawHost = String(rawHost.dropFirst().dropLast())
        }
        guard !rawHost.isEmpty else { return nil }
        self.scheme = scheme
        self.host = rawHost
        self.port = url.port ?? (scheme == "https" ? 443 : 80)
    }

    var rootURL: URL {
        let defaultPort = scheme == "https" ? 443 : 80
        let portPart = port == defaultPort ? "" : ":\(port)"
        if let url = URL(string: "\(scheme)://\(uriHost)\(portPart)/") {
            return url
        }
        return URL(string: "https://localhost/")!
    }

    func wsURL(path: String, queryItems: [URLQueryItem] = []) -> URL? {
        let wsScheme = scheme == "https" ? "wss" : "ws"
        let defaultPort = scheme == "https" ? 443 : 80
        let portPart = port == defaultPort ? "" : ":\(port)"
        guard var comps = URLComponents(string: "\(wsScheme)://\(uriHost)\(portPart)\(path)") else { return nil }
        if !queryItems.isEmpty { comps.queryItems = queryItems }
        return comps.url
    }

    func apiURL(path: String, queryItems: [URLQueryItem] = []) -> URL? {
        let defaultPort = scheme == "https" ? 443 : 80
        let portPart = port == defaultPort ? "" : ":\(port)"
        guard var comps = URLComponents(string: "\(scheme)://\(uriHost)\(portPart)\(path)") else { return nil }
        if !queryItems.isEmpty { comps.queryItems = queryItems }
        return comps.url
    }

    var isEncrypted: Bool { scheme == "https" }

    var pushId: String { "\(scheme)://\(uriHost):\(port)" }
}

enum NavigationDecision: Equatable, Sendable {
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
