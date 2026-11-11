import Foundation

enum AnswerOutcome: Equatable {
    case sent(agent: String?, working: Bool, replay: Bool)
    case alreadyAnswered
    case alreadyUsed
    case expired
    case notSent
}

enum AnswerClient {
    static let capHeader = "X-Carnivore-Cap"
    static let actPath = "/api/v1/notify/act"
    static let cardPath = "/api/v1/notify/card"

    static func request(base: URL, path: String, method: String, cap: String, body: Data? = nil, timeout: TimeInterval = 20) -> URLRequest {
        var req = URLRequest(url: URL(string: path, relativeTo: base)!.absoluteURL, timeoutInterval: timeout)
        req.httpMethod = method
        req.setValue(cap, forHTTPHeaderField: capHeader)
        req.cachePolicy = .reloadIgnoringLocalCacheData
        if let body {
            req.httpBody = body
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        return req
    }

    static func actBody(action: String, text: String?) -> Data {
        var object: [String: String] = ["action": action]
        if let text, !text.isEmpty { object["text"] = text }
        return (try? JSONSerialization.data(withJSONObject: object)) ?? Data()
    }

    static func outcome(status: Int, body: Data) -> AnswerOutcome {
        let object = (try? JSONSerialization.jsonObject(with: body)) as? [String: Any]
        switch status {
        case 200:
            return .sent(agent: object?["agent"] as? String, working: (object?["working"] as? Bool) ?? false,
                         replay: (object?["replay"] as? Bool) ?? false)
        case 409: return (object?["error"] as? String) == "already_used" ? .alreadyUsed : .alreadyAnswered
        case 410: return .expired
        default: return .notSent
        }
    }

    static func act(base: URL, cap: String, action: String, text: String?, session: URLSession = .shared) async -> AnswerOutcome {
        let req = request(base: base, path: actPath, method: "POST", cap: cap, body: actBody(action: action, text: text))
        guard let (data, response) = try? await session.data(for: req), let http = response as? HTTPURLResponse else { return .notSent }
        return outcome(status: http.statusCode, body: data)
    }

    static func fetch(base: URL, path: String, cap: String, timeout: TimeInterval = 20, session: URLSession = .shared) async -> Data? {
        let req = request(base: base, path: path, method: "GET", cap: cap, timeout: timeout)
        guard let (data, response) = try? await session.data(for: req), (response as? HTTPURLResponse)?.statusCode == 200 else { return nil }
        return data
    }

    static func fetchCard(base: URL, cap: String, session: URLSession = .shared) async -> NotifyCard? {
        guard let data = await fetch(base: base, path: cardPath, cap: cap, session: session), data.count <= NotifyContract.limitCardFullBytes,
              let object = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return nil }
        return NotifyCard(raw: object)
    }

    static func fetchMedia(base: URL, cap: String, id: String, poster: Bool, timeout: TimeInterval = 20, session: URLSession = .shared) async -> Data? {
        await fetch(base: base, path: "/api/v1/notify/media/\(id)" + (poster ? "/poster" : ""), cap: cap, timeout: timeout, session: session)
    }
}
