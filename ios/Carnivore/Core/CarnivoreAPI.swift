import Foundation

enum APIError: Error, LocalizedError, Equatable, Sendable {
    case invalidURL
    case unauthenticated
    case linkPairingRequired
    case httpStatus(Int, String)
    case decodingFailed(String)
    case network(String)

    var errorDescription: String? {
        switch self {
        case .invalidURL: return "Invalid server URL"
        case .unauthenticated: return "Sign-in required"
        case .linkPairingRequired: return "Phone pairing required"
        case let .httpStatus(code, msg): return msg.isEmpty ? "Server error (\(code))" : msg
        case let .decodingFailed(msg): return "Unexpected response: \(msg)"
        case let .network(msg): return msg
        }
    }
}

actor CarnivoreAPI {
    let computer: Computer
    private let session: URLSession
    private var refreshTask: Task<AuthCredentials, Error>?
    private var pendingPairCookie: String?

    init(computer: Computer, session: URLSession = SecureSession.shared) {
        self.computer = computer
        self.session = session
    }

    var originId: String { computer.origin.pushId }

    func storedCredentials() -> AuthCredentials? {
        AuthKeychain.load(origin: originId)
    }

    func hasCredentials() -> Bool {
        storedCredentials()?.hasTokens == true
    }

    func hasLinkCookie() -> Bool {
        guard let c = storedCredentials()?.linkCookie else { return false }
        return !c.isEmpty
    }

    func adoptLinkCookie(_ cookieHeader: String) {
        AuthKeychain.saveLinkCookie(cookieHeader, origin: originId)
    }

    func signOut() async {
        if let creds = AuthKeychain.load(origin: originId), creds.hasTokens {
            _ = try? await rawRequest(
                path: "/api/v1/auth/logout",
                method: "POST",
                jsonBody: ["refresh_token": creds.refreshToken],
                auth: creds
            )
        }
        AuthKeychain.clearTokensPreservingLinkCookie(origin: originId)
    }


    struct PairStatusDTO: Decodable, Sendable {
        let paired: Bool
        let pending: Bool
    }

    enum PairClaimOutcome: Equatable, Sendable {
        case pending
        case alreadyPaired
    }

    func checkPairStatus() async -> PairStatusDTO {
        guard computer.kind == .relay,
              let url = computer.origin.apiURL(path: "/pair/status") else {
            return PairStatusDTO(paired: true, pending: false)
        }
        var req = URLRequest(url: url, timeoutInterval: 10)
        req.httpMethod = "GET"
        let cookies = [AuthKeychain.load(origin: originId)?.linkCookie, pendingPairCookie]
            .compactMap { $0 }.filter { !$0.isEmpty }
        if !cookies.isEmpty {
            req.setValue(cookies.joined(separator: "; "), forHTTPHeaderField: "Cookie")
        }
        guard let (data, response) = try? await session.data(for: req),
              let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode),
              let dto = try? JSONDecoder().decode(PairStatusDTO.self, from: data) else {
            return PairStatusDTO(paired: hasLinkCookie(), pending: pendingPairCookie != nil)
        }
        return dto
    }

    @discardableResult
    func pairClaim(secret: String, deviceLabel: String) async throws -> PairClaimOutcome {
        guard let url = computer.origin.apiURL(path: "/pair/claim") else { throw APIError.invalidURL }
        var req = URLRequest(url: url, timeoutInterval: 15)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("\(computer.origin.scheme)://\(computer.origin.uriHost)", forHTTPHeaderField: "Origin")
        if let existing = AuthKeychain.load(origin: originId)?.linkCookie {
            req.setValue(existing, forHTTPHeaderField: "Cookie")
        }
        req.httpBody = try JSONSerialization.data(withJSONObject: ["secret": secret, "label": deviceLabel])
        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse else { throw APIError.network("No response") }
        guard (200...299).contains(http.statusCode) else {
            throw APIError.httpStatus(http.statusCode, Self.friendlyError(status: http.statusCode, data: data))
        }
        if let cookie = Self.extractCookie(named: "__Host-cc_pair", from: http) {
            pendingPairCookie = cookie
        }
        if let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           (obj["status"] as? String) == "already_paired" {
            return .alreadyPaired
        }
        return .pending
    }

    @discardableResult
    func pairCode(code: String, deviceLabel: String) async throws -> PairClaimOutcome {
        guard let url = computer.origin.apiURL(path: "/pair/code") else { throw APIError.invalidURL }
        var req = URLRequest(url: url, timeoutInterval: 15)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("\(computer.origin.scheme)://\(computer.origin.uriHost)", forHTTPHeaderField: "Origin")
        if let existing = AuthKeychain.load(origin: originId)?.linkCookie {
            req.setValue(existing, forHTTPHeaderField: "Cookie")
        }
        req.httpBody = try JSONSerialization.data(withJSONObject: ["code": code, "label": deviceLabel])
        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse else { throw APIError.network("No response") }
        guard (200...299).contains(http.statusCode) else {
            throw APIError.httpStatus(http.statusCode, Self.friendlyError(status: http.statusCode, data: data))
        }
        if let cookie = Self.extractCookie(named: "__Host-cc_pair", from: http) {
            pendingPairCookie = cookie
        }
        if let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           (obj["status"] as? String) == "already_paired" {
            return .alreadyPaired
        }
        return .pending
    }

    func pairVerify(totpCode: String) async throws -> AuthCredentials {
        guard let url = computer.origin.apiURL(path: "/pair/verify") else { throw APIError.invalidURL }
        var req = URLRequest(url: url, timeoutInterval: 15)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("\(computer.origin.scheme)://\(computer.origin.uriHost)", forHTTPHeaderField: "Origin")
        guard let pending = pendingPairCookie, !pending.isEmpty else {
            throw APIError.httpStatus(403, "Pairing session expired — scan the QR code or enter a fresh 8-char code.")
        }
        req.setValue(pending, forHTTPHeaderField: "Cookie")
        req.httpBody = try JSONSerialization.data(withJSONObject: ["code": totpCode])
        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse else { throw APIError.network("No response") }
        guard (200...299).contains(http.statusCode) else {
            let detail = Self.extractDetail(from: data)
            if detail == "pairing_dead" || detail == "no_pending" {
                pendingPairCookie = nil
            }
            throw APIError.httpStatus(http.statusCode, Self.friendlyError(status: http.statusCode, data: data))
        }
        let dto = try JSONDecoder().decode(PairVerifyResponseDTO.self, from: data)
        guard let access = dto.access_token, let refresh = dto.refresh_token else {
            throw APIError.decodingFailed("Server paired but returned no tokens")
        }
        let linkCookie = Self.extractCookie(named: "__Host-cc_link", from: http)
            ?? AuthKeychain.load(origin: originId)?.linkCookie
        if let statusToken = dto.status_token {
            StatusKeyStore.set(statusToken, origin: originId)
        }
        let creds = AuthCredentials(
            accessToken: access,
            refreshToken: refresh,
            linkCookie: linkCookie,
            expiresAt: Date().addingTimeInterval(TimeInterval(dto.expires_in ?? 900))
        )
        AuthKeychain.save(creds, origin: originId)
        pendingPairCookie = nil
        return creds
    }

    func verifyTOTP(code: String) async throws -> AuthCredentials {
        guard let url = computer.origin.apiURL(path: "/api/v1/auth/verify") else { throw APIError.invalidURL }
        var req = URLRequest(url: url, timeoutInterval: 15)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let existingCookie = AuthKeychain.load(origin: originId)?.linkCookie {
            req.setValue(existingCookie, forHTTPHeaderField: "Cookie")
        }
        req.httpBody = try JSONSerialization.data(withJSONObject: ["code": code])
        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse else { throw APIError.network("No response") }
        if (http.statusCode == 401 || http.statusCode == 403 || http.statusCode == 302),
           computer.kind == .relay,
           AuthKeychain.load(origin: originId)?.linkCookie == nil {
            throw APIError.linkPairingRequired
        }
        guard (200...299).contains(http.statusCode) else {
            throw APIError.httpStatus(http.statusCode, Self.friendlyError(status: http.statusCode, data: data))
        }
        let dto = try JSONDecoder().decode(AuthTokensDTO.self, from: data)
        let existing = AuthKeychain.load(origin: originId)
        let creds = AuthCredentials(
            accessToken: dto.access_token,
            refreshToken: dto.refresh_token ?? existing?.refreshToken ?? "",
            linkCookie: existing?.linkCookie,
            expiresAt: Date().addingTimeInterval(TimeInterval(dto.expires_in ?? 900))
        )
        AuthKeychain.save(creds, origin: originId)
        return creds
    }

    func validCredentials(forceRefresh: Bool = false) async throws -> AuthCredentials {
        guard let current = AuthKeychain.load(origin: originId), current.hasTokens else {
            throw APIError.unauthenticated
        }
        if !forceRefresh && !current.isExpiringSoon {
            return current
        }
        if let inFlight = refreshTask {
            return try await inFlight.value
        }
        let task = Task<AuthCredentials, Error> {
            try await performRefresh(current: current)
        }
        refreshTask = task
        defer { refreshTask = nil }
        return try await task.value
    }

    private func performRefresh(current: AuthCredentials) async throws -> AuthCredentials {
        guard !current.refreshToken.isEmpty else { throw APIError.unauthenticated }
        guard let url = computer.origin.apiURL(path: "/api/v1/auth/refresh") else { throw APIError.invalidURL }
        var req = URLRequest(url: url, timeoutInterval: 15)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let cookie = current.linkCookie { req.setValue(cookie, forHTTPHeaderField: "Cookie") }
        req.httpBody = try JSONSerialization.data(withJSONObject: ["refresh_token": current.refreshToken])
        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse else { throw APIError.network("No response") }
        if http.statusCode == 401 || http.statusCode == 403 {
            AuthKeychain.remove(origin: originId)
            throw APIError.unauthenticated
        }
        guard (200...299).contains(http.statusCode) else {
            throw APIError.httpStatus(http.statusCode, Self.extractDetail(from: data))
        }
        let dto = try JSONDecoder().decode(AuthTokensDTO.self, from: data)
        let updated = AuthCredentials(
            accessToken: dto.access_token,
            refreshToken: dto.refresh_token ?? current.refreshToken,
            linkCookie: current.linkCookie,
            expiresAt: Date().addingTimeInterval(TimeInterval(dto.expires_in ?? 900))
        )
        AuthKeychain.save(updated, origin: originId)
        return updated
    }


    private func rawRequest(
        path: String,
        method: String = "GET",
        queryItems: [URLQueryItem] = [],
        jsonBody: Any? = nil,
        auth: AuthCredentials,
        timeout: TimeInterval = 20
    ) async throws -> (Data, HTTPURLResponse) {
        guard let url = computer.origin.apiURL(path: path, queryItems: queryItems) else {
            throw APIError.invalidURL
        }
        var req = URLRequest(url: url, timeoutInterval: timeout)
        req.httpMethod = method
        req.setValue("Bearer \(auth.accessToken)", forHTTPHeaderField: "Authorization")
        if let cookie = auth.linkCookie {
            req.setValue(cookie, forHTTPHeaderField: "Cookie")
        }
        if let jsonBody {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: jsonBody)
        }
        let (data, response): (Data, URLResponse)
        do {
            (data, response) = try await session.data(for: req)
        } catch {
            throw APIError.network(error.localizedDescription)
        }
        guard let http = response as? HTTPURLResponse else {
            throw APIError.network("Invalid HTTP response")
        }
        return (data, http)
    }

    private func authedRequest(
        path: String,
        method: String = "GET",
        queryItems: [URLQueryItem] = [],
        jsonBody: Any? = nil,
        timeout: TimeInterval = 20
    ) async throws -> Data {
        var creds = try await validCredentials()
        var (data, http) = try await rawRequest(
            path: path, method: method, queryItems: queryItems, jsonBody: jsonBody, auth: creds, timeout: timeout
        )
        if http.statusCode == 401 {
            creds = try await validCredentials(forceRefresh: true)
            (data, http) = try await rawRequest(
                path: path, method: method, queryItems: queryItems, jsonBody: jsonBody, auth: creds, timeout: timeout
            )
            if http.statusCode == 401 {
                throw APIError.unauthenticated
            }
        }
        if http.statusCode == 403 && computer.kind == .relay && creds.linkCookie == nil {
            throw APIError.linkPairingRequired
        }
        guard (200...299).contains(http.statusCode) else {
            throw APIError.httpStatus(http.statusCode, Self.extractDetail(from: data))
        }
        return data
    }

    private func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            throw APIError.decodingFailed(error.localizedDescription)
        }
    }


    func fetchSessionListing() async throws -> SessionListingSnapshotDTO {
        let data = try await authedRequest(path: "/api/v1/sessions/listing")
        return try decode(SessionListingSnapshotDTO.self, from: data)
    }

    func createSession(workingDir: String, projectName: String?, agentType: String, openingPrompt: String?) async throws -> SessionInnerDTO {
        var body: [String: Any] = [
            "working_dir": workingDir,
            "agent_type": agentType,
            "auto_start_claude": agentType != "shell",
        ]
        if let projectName, !projectName.isEmpty { body["project_name"] = projectName }
        if let openingPrompt, !openingPrompt.isEmpty { body["opening_prompt"] = openingPrompt }
        let data = try await authedRequest(path: "/api/v1/sessions", method: "POST", jsonBody: body, timeout: 30)
        return try decode(SessionInnerDTO.self, from: data)
    }

    func killSession(id: String) async throws {
        _ = try await authedRequest(
            path: "/api/v1/sessions",
            method: "DELETE",
            queryItems: [URLQueryItem(name: "session_id", value: id)]
        )
    }

    func sleepSession(uuid: String) async throws {
        _ = try await authedRequest(path: "/api/v1/sessions/\(Self.encodeSegment(uuid))/sleep", method: "POST")
    }

    func wakeSession(uuid: String) async throws {
        _ = try await authedRequest(path: "/api/v1/sessions/\(Self.encodeSegment(uuid))/wake", method: "POST", timeout: 30)
    }

    func renameSession(id: String, newName: String) async throws {
        _ = try await authedRequest(
            path: "/api/v1/sessions/\(Self.encodeSegment(id))/name",
            method: "PATCH",
            jsonBody: ["new_name": newName]
        )
    }

    func interruptSession(id: String) async throws {
        _ = try await authedRequest(path: "/api/v1/sessions/\(Self.encodeSegment(id))/interrupt", method: "POST")
    }

    func restartSession(uuid: String) async throws {
        _ = try await authedRequest(path: "/api/v1/sessions/\(Self.encodeSegment(uuid))/restart", method: "POST", timeout: 30)
    }

    func setSessionUnread(name: String, unread: Bool) async throws {
        _ = try await authedRequest(
            path: "/api/v1/sessions/\(Self.encodeSegment(name))/unread",
            method: "PATCH",
            jsonBody: ["unread": unread]
        )
    }

    func sendCommand(_ command: String) async throws {
        _ = try await authedRequest(
            path: "/api/v1/sessions/command",
            method: "POST",
            jsonBody: ["command": command]
        )
    }

    func uploadFile(sessionId: String, filename: String, mimeType: String, fileData: Data) async throws -> UploadResponseDTO {
        let creds = try await validCredentials()
        guard let url = computer.origin.apiURL(
            path: "/api/v1/sessions/upload-file",
            queryItems: [URLQueryItem(name: "session_id", value: sessionId)]
        ) else { throw APIError.invalidURL }

        let boundary = "CarnivoreBoundary-\(UUID().uuidString)"
        var body = Data()
        body.append(Data("--\(boundary)\r\n".utf8))
        body.append(Data("Content-Disposition: form-data; name=\"file\"; filename=\"\(NotifyActions.safeFilename(filename))\"\r\n".utf8))
        body.append(Data("Content-Type: \(mimeType)\r\n\r\n".utf8))
        body.append(fileData)
        body.append(Data("\r\n--\(boundary)--\r\n".utf8))

        var req = URLRequest(url: url, timeoutInterval: 45)
        req.httpMethod = "POST"
        req.setValue("Bearer \(creds.accessToken)", forHTTPHeaderField: "Authorization")
        if let cookie = creds.linkCookie { req.setValue(cookie, forHTTPHeaderField: "Cookie") }
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        req.httpBody = body

        let (data, response) = try await session.data(for: req)
        guard let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) else {
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            throw APIError.httpStatus(code, Self.extractDetail(from: data))
        }
        return try decode(UploadResponseDTO.self, from: data)
    }


    func fetchApprovals() async throws -> ApprovalsResponseDTO {
        let data = try await authedRequest(path: "/api/v1/approvals")
        return try decode(ApprovalsResponseDTO.self, from: data)
    }

    func answerDialog(sessionId: String, fingerprint: String, choice: [String: Any]) async throws {
        _ = try await authedRequest(
            path: "/api/v1/sessions/\(Self.encodeSegment(sessionId))/dialog/answer",
            method: "POST",
            jsonBody: [
                "fingerprint": fingerprint,
                "choice": choice,
                "source": "owner_phone",
            ]
        )
    }

    func approveAgentAction(id: String, typed: String? = nil) async throws {
        let body: [String: Any]? = typed.map { ["typed": $0] }
        _ = try await authedRequest(
            path: "/api/v1/agent-actions/\(Self.encodeSegment(id))/approve",
            method: "POST",
            jsonBody: body
        )
    }

    func denyAgentAction(id: String) async throws {
        _ = try await authedRequest(
            path: "/api/v1/agent-actions/\(Self.encodeSegment(id))/deny",
            method: "POST"
        )
    }


    func fetchBeastMode() async throws -> BeastModeStateDTO {
        let data = try await authedRequest(path: "/api/v1/beast-mode")
        return try decode(BeastModeStateDTO.self, from: data)
    }

    func setBeastMode(enabled: Bool, prompts: Bool = false, hours: Int? = nil) async throws -> BeastModeStateDTO {
        var body: [String: Any] = ["enabled": enabled, "prompts": prompts]
        if let hours { body["hours"] = hours }
        let data = try await authedRequest(path: "/api/v1/beast-mode", method: "PUT", jsonBody: body)
        return try decode(BeastModeStateDTO.self, from: data)
    }


    func fetchBackgroundWork(sessionId: String) async throws -> BackgroundWorkDTO {
        let data = try await authedRequest(path: "/api/v1/sessions/\(Self.encodeSegment(sessionId))/background-work")
        return try decode(BackgroundWorkDTO.self, from: data)
    }

    func terminateBackgroundProcess(sessionId: String, pid: Int, start: String) async throws {
        _ = try await authedRequest(
            path: "/api/v1/sessions/\(Self.encodeSegment(sessionId))/background-work/\(pid)/terminate",
            method: "POST",
            jsonBody: ["start": start]
        )
    }

    func stopLeftoverShells(sessionId: String) async throws {
        _ = try await authedRequest(
            path: "/api/v1/sessions/\(Self.encodeSegment(sessionId))/background-work/stop-leftovers",
            method: "POST",
            jsonBody: [String: Any]()
        )
    }

    func fetchGitStatus(sessionId: String) async throws -> SessionGitStatusDTO {
        let data = try await authedRequest(path: "/api/v1/sessions/\(Self.encodeSegment(sessionId))/git-status")
        return try decode(SessionGitStatusDTO.self, from: data)
    }

    func fetchGitDiff(sessionId: String, path: String, staged: Bool = false) async throws -> SessionGitDiffDTO {
        let data = try await authedRequest(
            path: "/api/v1/sessions/\(Self.encodeSegment(sessionId))/git-diff",
            queryItems: [
                URLQueryItem(name: "path", value: path),
                URLQueryItem(name: "staged", value: staged ? "true" : "false"),
            ]
        )
        return try decode(SessionGitDiffDTO.self, from: data)
    }


    func fetchPackActivity() async throws -> PackActivityDTO {
        let data = try await authedRequest(
            path: "/api/v1/pack/activity",
            queryItems: [URLQueryItem(name: "days", value: "3"), URLQueryItem(name: "limit", value: "100")]
        )
        return try decode(PackActivityDTO.self, from: data)
    }

    func fetchSwarmRoster() async throws -> SwarmRosterDTO {
        let data = try await authedRequest(path: "/api/v1/swarm/roster")
        return try decode(SwarmRosterDTO.self, from: data)
    }

    func sendSwarmMessage(agentId: String, body: String) async throws {
        _ = try await authedRequest(
            path: "/api/v1/swarm/agents/\(Self.encodeSegment(agentId))/messages",
            method: "POST",
            jsonBody: ["body": body]
        )
    }

    func fetchProjects() async throws -> [ProjectDTO] {
        let data = try await authedRequest(path: "/api/v1/projects")
        if let wrapped = try? JSONDecoder().decode(ProjectsListResponseDTO.self, from: data), let list = wrapped.projects {
            return list
        }
        return (try? JSONDecoder().decode([ProjectDTO].self, from: data)) ?? []
    }


    func registerNativeDevice(_ body: NativeDeviceRegisterBody) async throws -> String {
        let encoded = try JSONEncoder().encode(body)
        let jsonObject = try JSONSerialization.jsonObject(with: encoded)
        let data = try await authedRequest(path: "/api/v1/native-devices", method: "POST", jsonBody: jsonObject)
        return try decode(NativeDevicePublicDTO.self, from: data).id
    }


    private static func encodeSegment(_ s: String) -> String {
        s.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed.subtracting(CharacterSet(charactersIn: "/?&#"))) ?? s
    }

    private static func extractDetail(from data: Data) -> String {
        guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return "" }
        if let detail = obj["detail"] as? String { return detail }
        if let detail = obj["detail"] as? [String: Any], let msg = detail["message"] as? String ?? detail["reason"] as? String ?? detail["code"] as? String {
            return msg
        }
        return (obj["message"] as? String) ?? (obj["error"] as? String) ?? ""
    }

    static func friendlyError(status: Int, data: Data) -> String {
        let raw = extractDetail(from: data)
        switch raw {
        case "joined_local_only":
            return "This computer is a Pack member and cannot pair directly. Scan the QR code on your Main computer instead — it already gives you access to every computer in your Pack."
        case "code_reused": return "That code was already used — wait for the next 30-second code."
        case "no_pending": return "Pairing window expired — scan the QR code or enter a new 8-char code."
        case "pairing_dead": return "Too many wrong codes for this pairing — open a new pairing window on your computer."
        case "link_used": return "QR code expired or already used — scan the current QR code on your computer."
        case "wrong_code": return "Invalid 8-character pairing code — check the code on your computer."
        default:
            if status == 429 { return "Too many attempts — wait a minute and try again." }
            if status == 401 { return raw.isEmpty ? "Invalid authenticator code." : raw }
            return raw.isEmpty ? "Server error (\(status))." : raw
        }
    }

    static func extractCookie(named name: String, from response: HTTPURLResponse) -> String? {
        if let url = response.url {
            let headers = response.allHeaderFields as? [String: String] ?? [:]
            let cookies = HTTPCookie.cookies(withResponseHeaderFields: headers, for: url)
            if let hit = cookies.first(where: { $0.name == name }), !hit.value.isEmpty {
                return "\(hit.name)=\(hit.value)"
            }
        }
        for (k, v) in response.allHeaderFields {
            guard String(describing: k).lowercased() == "set-cookie",
                  let headerVal = v as? String else { continue }
            if let hit = parseCookieValue(named: name, fromSetCookieHeader: headerVal) {
                return hit
            }
        }
        return nil
    }

    static func parseCookieValue(named name: String, fromSetCookieHeader header: String) -> String? {
        let pattern = "(?:^|[,;\\s])" + NSRegularExpression.escapedPattern(for: name) + "=([^;,\\s]+)"
        guard let regex = try? NSRegularExpression(pattern: pattern),
              let match = regex.firstMatch(in: header, range: NSRange(header.startIndex..., in: header)),
              let valRange = Range(match.range(at: 1), in: header) else {
            return nil
        }
        let value = String(header[valRange])
        return value.isEmpty ? nil : "\(name)=\(value)"
    }
}
