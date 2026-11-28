import Foundation

struct NotifyMedia: Equatable, Sendable {
    let id: String
    let mime: String
    let bytes: Int
    var w: Int? = nil
    var h: Int? = nil
    var dur: Double? = nil

    static func isValidId(_ value: String) -> Bool {
        value.range(of: "\\A[0-9a-f]{32}\\z", options: .regularExpression) != nil
    }
}

struct NotifySettle: Equatable, Sendable {
    let place: String
    let agent: String
    let working: Bool

    var line: String {
        switch place {
        case "computer": return Strings.cardStateSettled
        case "phone": return Strings.cardStateAlreadyUsed
        default: return Strings.cardStateAnswered
        }
    }
}

struct NotifyEnvelope: Equatable, Sendable {
    var kind: NotifyKind
    var type: String? = nil
    var sub: String? = nil
    var level: String? = nil
    var sound: String? = nil
    var cap: String? = nil
    var ttl: Double? = nil
    var acts: [[String]] = []
    var cardJSON: Data? = nil
    var more = false
    var media: NotifyMedia? = nil
    var settle: NotifySettle? = nil

    static func parse(_ object: [String: Any]) -> NotifyEnvelope? {
        guard (object["v"] as? Int) == NotifyContract.version,
              let kind = (object["kind"] as? String).flatMap(NotifyKind.init(rawValue:)) else { return nil }
        var env = NotifyEnvelope(kind: kind)
        env.type = object["type"] as? String
        env.sub = (object["sub"] as? String).map { String($0.prefix(NotifyContract.limitSub)) }
        env.level = (object["lv"] as? String).flatMap { NotifyContract.levels[$0] != nil ? $0 : nil }
        env.sound = (object["snd"] as? String).flatMap { NotifyContract.sounds.contains($0) ? $0 : nil }
        if let cap = object["cap"] as? String, cap.count == NotifyContract.limitCap, cap.allSatisfy(isBase64URL) { env.cap = cap }
        env.ttl = object["ttl"] as? Double
        env.acts = ((object["acts"] as? [[String]]) ?? []).filter { $0.count == 2 }.prefix(NotifyContract.limitActs)
            .map { [$0[0], String($0[1].prefix(NotifyContract.limitActLabel))] }
        if let card = object["card"] as? [String: Any] { env.cardJSON = try? JSONSerialization.data(withJSONObject: card) }
        env.more = (object["more"] as? Bool) ?? false
        if let m = object["media"] as? [String: Any],
           let id = m["id"] as? String, NotifyMedia.isValidId(id),
           let mime = m["mime"] as? String,
           let bytes = m["bytes"] as? Int, bytes >= 0 {
            env.media = NotifyMedia(id: id, mime: mime, bytes: bytes, w: m["w"] as? Int, h: m["h"] as? Int, dur: m["dur"] as? Double)
        }
        if let s = object["settle"] as? [String: Any], let place = s["where"] as? String, let agent = s["agent"] as? String {
            env.settle = NotifySettle(place: place, agent: agent, working: (s["working"] as? Bool) ?? false)
        }
        return env
    }

    private static func isBase64URL(_ c: Character) -> Bool { c.isASCII && (c.isLetter || c.isNumber || c == "-" || c == "_") }
}

struct NotifyCard {
    let raw: [String: Any]

    init(raw: [String: Any]) { self.raw = raw }

    init(json: Data?) {
        raw = (json.flatMap { try? JSONSerialization.jsonObject(with: $0) } as? [String: Any]) ?? [:]
    }

    func string(_ key: String) -> String? { raw[key] as? String }
    func int(_ key: String) -> Int? { (raw[key] as? Int) ?? (raw[key] as? Double).map { Int($0) } }
    func bool(_ key: String) -> Bool { (raw[key] as? Bool) ?? false }
    func strings(_ key: String) -> [String] { (raw[key] as? [String]) ?? [] }
    func rows(_ key: String) -> [[String]] { (raw[key] as? [[String]]) ?? [] }
    func intRows(_ key: String) -> [[Int]] { ((raw[key] as? [[Any]]) ?? []).map { $0.compactMap { ($0 as? Int) ?? ($0 as? Double).map(Int.init) } } }
    var isEmpty: Bool { raw.isEmpty }
}
