import Foundation

struct NotifyUserInfo: Equatable, Sendable {
    var kind: NotifyKind
    var cap: String?
    var base: URL?
    var ttl: Double?
    var cardJSON: Data?
    var acts: [[String]]
    var media: NotifyMedia?
    var settle: NotifySettle?

    static func isAllowedBase(_ url: URL) -> Bool {
        guard let scheme = url.scheme?.lowercased(), let host = url.host?.lowercased() else { return false }
        let port = url.port ?? (scheme == "https" ? 443 : 80)
        if scheme == "https", port == 443,
           host.range(of: "\\A[a-z2-7]{26}\\.link\\.carnivore\\.ai\\z", options: .regularExpression) != nil {
            return true
        }
        #if DEBUG && targetEnvironment(simulator)
        if (scheme == "http" || scheme == "https"), (host == "127.0.0.1" || host == "localhost") {
            return true
        }
        if scheme == "https", port == 443, host.hasSuffix(".link.carnivore.ai") {
            return true
        }
        #endif
        return false
    }

    static func encode(_ env: NotifyEnvelope, origin: String, fullCard: Data? = nil) -> [String: String] {
        var out: [String: String] = ["kind": env.kind.rawValue, "base": origin]
        if let cap = env.cap { out["cap"] = cap }
        if let ttl = env.ttl { out["ttl"] = String(ttl) }
        if let card = fullCard ?? env.cardJSON, let text = String(data: card, encoding: .utf8) { out["card"] = text }
        if !env.acts.isEmpty, let data = try? JSONSerialization.data(withJSONObject: env.acts), let text = String(data: data, encoding: .utf8) { out["acts"] = text }
        if let m = env.media, NotifyMedia.isValidId(m.id) {
            var object: [String: Any] = ["id": m.id, "mime": m.mime, "bytes": m.bytes]
            if let w = m.w { object["w"] = w }
            if let h = m.h { object["h"] = h }
            if let d = m.dur { object["dur"] = d }
            if let data = try? JSONSerialization.data(withJSONObject: object), let text = String(data: data, encoding: .utf8) { out["media"] = text }
        }
        if let s = env.settle, let data = try? JSONSerialization.data(withJSONObject: ["where": s.place, "agent": s.agent, "working": s.working]),
           let text = String(data: data, encoding: .utf8) { out["settle"] = text }
        return out
    }

    init?(userInfo: [AnyHashable: Any], requireValidMAC: Bool = false) {
        if requireValidMAC, !NotificationMAC.verify(userInfo) { return nil }
        guard let kind = (userInfo["kind"] as? String).flatMap(NotifyKind.init(rawValue:)) else { return nil }
        self.kind = kind
        cap = userInfo["cap"] as? String
        if let rawBase = userInfo["base"] as? String, let parsed = URL(string: rawBase), Self.isAllowedBase(parsed) {
            base = parsed
        } else {
            base = nil
        }
        ttl = (userInfo["ttl"] as? String).flatMap(Double.init)
        cardJSON = (userInfo["card"] as? String)?.data(using: .utf8)
        func object(_ key: String) -> [String: Any]? {
            (userInfo[key] as? String)?.data(using: .utf8).flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]
        }
        acts = (((userInfo["acts"] as? String)?.data(using: .utf8).flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [[String]]) ?? [])
            .filter { $0.count >= 2 }
        media = object("media").flatMap { m in
            guard let id = m["id"] as? String, NotifyMedia.isValidId(id),
                  let mime = m["mime"] as? String, let bytes = m["bytes"] as? Int, bytes >= 0 else { return nil }
            return NotifyMedia(id: id, mime: mime, bytes: bytes, w: m["w"] as? Int, h: m["h"] as? Int, dur: m["dur"] as? Double)
        }
        settle = object("settle").flatMap { s in
            guard let place = s["where"] as? String, let agent = s["agent"] as? String else { return nil }
            return NotifySettle(place: place, agent: agent, working: (s["working"] as? Bool) ?? false)
        }
    }

    func isExpired(now: Date = Date()) -> Bool { ttl.map { now.timeIntervalSince1970 >= $0 } ?? false }
}
