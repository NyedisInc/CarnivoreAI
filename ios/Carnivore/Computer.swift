import Foundation

enum ComputerKind: String, Codable, CaseIterable, Sendable {
    case relay, lan, https

    var label: String {
        switch self {
        case .relay: return Strings.kindRelay
        case .lan: return Strings.kindLan
        case .https: return Strings.kindHttps
        }
    }
}

enum AddressError: Error, Equatable, Sendable {
    case empty
    case notALinkHost
    case notHttps
    case notHttpOrHttps
    case badHost
    case hasCredentials
}

extension AddressError {
    var message: String {
        switch self {
        case .empty: return Strings.addressEmpty
        case .notALinkHost: return Strings.addressNotALinkHost
        case .notHttps: return Strings.addressNotHttps
        case .notHttpOrHttps: return Strings.addressNotHttpOrHttps
        case .badHost: return Strings.addressBadHost
        case .hasCredentials: return Strings.addressHasCredentials
        }
    }
}

struct Computer: Codable, Identifiable, Equatable, Hashable, Sendable {
    var id = UUID()
    var name: String
    var kind: ComputerKind
    var origin: Origin

    var isUnencrypted: Bool { !origin.isEncrypted }

    var isRawRelayHashName: Bool {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty { return true }
        let lower = trimmed.lowercased()
        if lower == origin.host.lowercased(), kind == .relay { return true }
        return lower.range(of: "\\A[a-z2-7]{26}\\.link\\.carnivore\\.ai\\z", options: .regularExpression) != nil
    }

    var displayName: String {
        isRawRelayHashName ? "My Computer" : name
    }

    var shortAddress: String {
        if kind == .relay, origin.host.hasSuffix(".link.carnivore.ai") {
            let prefix = String(origin.host.prefix(6))
            return "Relay · \(prefix)…"
        }
        return origin.host
    }
}

enum AddressParser {
    private static let linkHost = try! NSRegularExpression(
        pattern: "\\A[a-z2-7]{26}\\.link\\.carnivore\\.ai\\z")
    private static let schemePrefix = try! NSRegularExpression(
        pattern: "\\A[A-Za-z][A-Za-z0-9+.-]*:(?!\\d+(/|\\z))")
    private static let hostChars = try! NSRegularExpression(
        pattern: "\\A[a-z0-9]([a-z0-9.-]*[a-z0-9])?\\z|\\A\\[[0-9a-f:]+\\]\\z|\\A[0-9a-f:]+\\z")

    static func parse(_ input: String, kind: ComputerKind) -> Result<Origin, AddressError> {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty { return .failure(.empty) }
        if text.contains("\n") || text.contains("\r") { return .failure(.badHost) }
        let hasScheme = schemePrefix.firstMatch(
            in: text, range: NSRange(text.startIndex..., in: text)) != nil
        if hasScheme, !(text.lowercased().hasPrefix("http://") || text.lowercased().hasPrefix("https://")) {
            return .failure(.notHttpOrHttps)
        }
        let withScheme: String
        switch kind {
        case .relay, .https: withScheme = hasScheme ? text : "https://" + text
        case .lan: withScheme = hasScheme ? text : "http://" + text
        }
        guard let comps = URLComponents(string: withScheme), let rawHost = comps.host?.lowercased(),
              !rawHost.isEmpty else { return .failure(.badHost) }
        if comps.user != nil || comps.password != nil { return .failure(.hasCredentials) }
        let host = (rawHost.hasPrefix("[") && rawHost.hasSuffix("]")) ? String(rawHost.dropFirst().dropLast()) : rawHost
        let range = NSRange(host.startIndex..., in: host)
        guard !host.isEmpty, hostChars.firstMatch(in: host, range: range) != nil else { return .failure(.badHost) }
        let scheme = comps.scheme?.lowercased() ?? ""
        switch kind {
        case .relay:
            if scheme != "https" { return .failure(.notHttps) }
            if linkHost.firstMatch(in: host, range: range) == nil { return .failure(.notALinkHost) }
        case .https:
            if scheme != "https" { return .failure(.notHttps) }
        case .lan:
            if scheme != "http" && scheme != "https" { return .failure(.notHttpOrHttps) }
        }
        let port = comps.port ?? (kind == .lan && scheme == "http" ? 8000 : (scheme == "https" ? 443 : 80))
        let uriHost = host.contains(":") ? "[\(host)]" : host
        let defaultPort = scheme == "https" ? 443 : 80
        let portPart = port == defaultPort ? "" : ":\(port)"
        guard let built = URL(string: "\(scheme)://\(uriHost)\(portPart)/"),
              let origin = Origin(url: built) else { return .failure(.badHost) }
        return .success(origin)
    }
}
