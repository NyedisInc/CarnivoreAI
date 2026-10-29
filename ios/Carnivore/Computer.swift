import Foundation

enum ComputerKind: String, Codable, CaseIterable {
    case relay, lan, https

    var label: String {
        switch self {
        case .relay: return Strings.kindRelay
        case .lan: return Strings.kindLan
        case .https: return Strings.kindHttps
        }
    }
}

enum AddressError: Error, Equatable {
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

struct Computer: Codable, Identifiable, Equatable {
    var id = UUID()
    var name: String
    var kind: ComputerKind
    var origin: Origin

    var isUnencrypted: Bool { !origin.isEncrypted }
}

enum AddressParser {
    private static let linkHost = try! NSRegularExpression(
        pattern: "^[a-z2-7]{26}\\.link\\.carnivore\\.ai$")
    private static let schemePrefix = try! NSRegularExpression(
        pattern: "^[A-Za-z][A-Za-z0-9+.-]*:(?!\\d+(/|$))")
    private static let hostChars = try! NSRegularExpression(
        pattern: "^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$|^\\[[0-9a-f:]+\\]$")

    static func parse(_ input: String, kind: ComputerKind) -> Result<Origin, AddressError> {
        let text = input.trimmingCharacters(in: .whitespacesAndNewlines)
        if text.isEmpty { return .failure(.empty) }
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
        guard let comps = URLComponents(string: withScheme), let host = comps.host?.lowercased(),
              !host.isEmpty else { return .failure(.badHost) }
        if comps.user != nil || comps.password != nil { return .failure(.hasCredentials) }
        let range = NSRange(host.startIndex..., in: host)
        guard hostChars.firstMatch(in: host, range: range) != nil else { return .failure(.badHost) }
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
        var url = comps
        url.path = ""
        url.query = nil
        url.fragment = nil
        if kind == .lan, comps.port == nil, scheme == "http" { url.port = 8000 }
        guard let built = url.url, let origin = Origin(url: built) else { return .failure(.badHost) }
        return .success(origin)
    }
}
