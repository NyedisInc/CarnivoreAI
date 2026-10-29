import Foundation

struct PendingTap: Equatable {
    let origin: String
    let path: String
}

final class TapRouter: ObservableObject {
    static let shared = TapRouter()
    @Published private(set) var pending: PendingTap?

    static func path(from userInfo: [AnyHashable: Any]) -> String? {
        let candidate = userInfo["path"] as? String
        return PathGuard.isSafe(candidate) ? candidate : nil
    }

    func tapped(userInfo: [AnyHashable: Any]) {
        if let path = Self.path(from: userInfo), let origin = userInfo["origin"] as? String, !origin.isEmpty {
            pending = PendingTap(origin: origin, path: path)
        }
    }

    func take(forOrigin origin: String) -> String? {
        guard let tap = pending, tap.origin == origin else { return nil }
        pending = nil
        return tap.path
    }

    func clear() { pending = nil }
}
