import Foundation

enum PairError: Error, Equatable {
    case notAPairingCode
    case unknownHost
    case badSecret
}

struct PairTarget: Equatable {
    let url: URL
    let origin: Origin
    let isKnown: Bool
    let kind: ComputerKind
    let needsConfirm: Bool
}

enum HostDecision: Equatable {
    case link, known, confirm, refuse
}

enum PairURL {
    private static let linkDomain = "link.carnivore.ai"
    private static let linkHost = try! NSRegularExpression(
        pattern: "\\A[a-z2-7]{26}\\.link\\.carnivore\\.ai\\z")
    private static let domainHost = try! NSRegularExpression(
        pattern: "\\A([a-z0-9]([a-z0-9-]*[a-z0-9])?\\.)+[a-z0-9-]*[a-z][a-z0-9-]*\\z")
    private static let secretShape = try! NSRegularExpression(pattern: "\\A[A-Za-z0-9_-]{32,128}\\z")

    static func hostDecision(_ origin: Origin, known: [Origin]) -> HostDecision {
        let host = origin.host
        let range = NSRange(host.startIndex..., in: host)
        let isHttps443 = origin.scheme == "https" && origin.port == 443
        if isHttps443, linkHost.firstMatch(in: host, range: range) != nil { return .link }
        if known.contains(origin) { return .known }
        if isHttps443, host.count <= 253, domainHost.firstMatch(in: host, range: range) != nil { return .confirm }
        return .refuse
    }

    static func parse(_ text: String, known: [Origin]) -> Result<PairTarget, PairError> {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let comps = URLComponents(string: trimmed), let url = comps.url,
              comps.path == "/pair", comps.percentEncodedQuery.map { $0.hasPrefix("link=") && !$0.contains("&") } ?? true,
              comps.user == nil, comps.password == nil,
              let origin = Origin(url: url) else { return .failure(.notAPairingCode) }
        guard let secret = comps.fragment,
              secretShape.firstMatch(in: secret, range: NSRange(secret.startIndex..., in: secret)) != nil
        else { return .failure(.badSecret) }
        if let relay = linkTarget(comps, secret: secret, scanned: origin, known: known) { return .success(relay) }
        return target(for: origin, url: url, known: known)
    }

    private static func linkTarget(_ comps: URLComponents, secret: String, scanned: Origin, known: [Origin]) -> PairTarget? {
        guard let query = comps.percentEncodedQuery else { return nil }
        let host = "\(query.dropFirst("link=".count)).\(linkDomain)"
        guard !isLinkHost(scanned.host),
              linkHost.firstMatch(in: host, range: NSRange(host.startIndex..., in: host)) != nil,
              let url = URL(string: "https://\(host)/pair#\(secret)"), let origin = Origin(url: url)
        else { return nil }
        return PairTarget(url: url, origin: origin, isKnown: known.contains(origin), kind: .relay, needsConfirm: false)
    }

    private static func isLinkHost(_ host: String) -> Bool {
        linkHost.firstMatch(in: host, range: NSRange(host.startIndex..., in: host)) != nil
    }

    static func manual(_ origin: Origin, known: [Origin]) -> Result<PairTarget, PairError> {
        guard let url = URL(string: "/pair", relativeTo: origin.rootURL)?.absoluteURL else {
            return .failure(.notAPairingCode)
        }
        return target(for: origin, url: url, known: known)
    }

    private static func target(for origin: Origin, url: URL, known: [Origin]) -> Result<PairTarget, PairError> {
        let decision = hostDecision(origin, known: known)
        if decision == .refuse { return .failure(.unknownHost) }
        return .success(PairTarget(url: url, origin: origin, isKnown: known.contains(origin),
                                   kind: decision == .link ? .relay : .https,
                                   needsConfirm: decision == .confirm))
    }
}
