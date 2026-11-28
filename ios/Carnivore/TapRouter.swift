import Foundation

struct PendingTap: Equatable, Sendable {
    let origin: String
    let path: String
    var sessionId: String? {
        let parts = path.split(separator: "/").map(String.init)
        if parts.count >= 2, (parts[0] == "session" || parts[0] == "sessions") {
            return parts[1].removingPercentEncoding ?? parts[1]
        }
        return nil
    }
}

enum DeepLink: Equatable, Sendable {
    case session(id: String)
    case inbox
    case pack
    case dictate(sessionId: String?)
    case settings
}

@MainActor
final class TapRouter: ObservableObject {
    static let shared = TapRouter()
    @Published private(set) var pending: PendingTap?
    @Published private(set) var pendingDeepLink: DeepLink?

    nonisolated static func path(from userInfo: [AnyHashable: Any]) -> String? {
        let candidate = userInfo["path"] as? String
        return PathGuard.isSafe(candidate) ? candidate : nil
    }

    func tapped(userInfo: [AnyHashable: Any], requireValidMAC: Bool = false) {
        if requireValidMAC, !NotificationMAC.verify(userInfo) { return }
        if let path = Self.path(from: userInfo), let origin = userInfo["origin"] as? String, !origin.isEmpty {
            pending = PendingTap(origin: origin, path: path)
        }
    }

    @discardableResult
    func handleURL(_ url: URL) -> Bool {
        guard url.scheme?.lowercased() == "carnivore",
              let host = url.host?.lowercased() else { return false }
        let comps = URLComponents(url: url, resolvingAgainstBaseURL: false)
        switch host {
        case "session":
            let raw = url.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
            let id = raw.isEmpty ? comps?.queryItems?.first(where: { $0.name == "id" })?.value : raw
            if let id, !id.isEmpty, id.count <= 200 {
                pendingDeepLink = .session(id: id)
                return true
            }
            return false
        case "inbox", "approvals":
            pendingDeepLink = .inbox
            return true
        case "pack", "swarm":
            pendingDeepLink = .pack
            return true
        case "dictate":
            let sid = comps?.queryItems?.first(where: { $0.name == "session" })?.value
            pendingDeepLink = .dictate(sessionId: sid)
            return true
        case "settings":
            pendingDeepLink = .settings
            return true
        default:
            return false
        }
    }

    func take(forOrigin origin: String) -> String? {
        guard let tap = pending, tap.origin == origin else { return nil }
        pending = nil
        return tap.path
    }

    func consumeDeepLink() -> DeepLink? {
        guard let current = pendingDeepLink else { return nil }
        pendingDeepLink = nil
        return current
    }

    func clear() { pending = nil }
}
