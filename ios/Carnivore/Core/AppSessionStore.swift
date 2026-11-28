import Foundation
import SwiftUI
import WebKit

struct WebAuthHandoff: Equatable, Sendable {
    let originId: String
    let credentials: AuthCredentials
    let overwriteLocalStorage: Bool
    let nonce: String

    init(originId: String, credentials: AuthCredentials, overwriteLocalStorage: Bool, nonce: String = UUID().uuidString) {
        self.originId = originId
        self.credentials = credentials
        self.overwriteLocalStorage = overwriteLocalStorage
        self.nonce = nonce
    }

    static func makeLinkCookie(origin: Origin, rawCookie: String?) -> HTTPCookie? {
        guard let rawCookie, !rawCookie.isEmpty, origin.scheme == "https" else { return nil }
        let value: String
        if rawCookie.hasPrefix("__Host-cc_link=") {
            value = String(rawCookie.dropFirst("__Host-cc_link=".count))
        } else if !rawCookie.contains("=") {
            value = rawCookie
        } else {
            return nil
        }
        guard !value.isEmpty else { return nil }
        let header = "__Host-cc_link=\(value); Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=31536000"
        return HTTPCookie.cookies(withResponseHeaderFields: ["Set-Cookie": header], for: origin.rootURL).first
    }

    static func makeSeedScript(origin: Origin, handoff: WebAuthHandoff) -> String? {
        let access = handoff.credentials.accessToken
        let refresh = handoff.credentials.refreshToken
        guard !access.isEmpty || !refresh.isEmpty else { return nil }

        let expectedOrigin: String
        if (origin.scheme == "https" && origin.port == 443) || (origin.scheme == "http" && origin.port == 80) {
            expectedOrigin = "\(origin.scheme)://\(origin.uriHost)"
        } else {
            expectedOrigin = "\(origin.scheme)://\(origin.uriHost):\(origin.port)"
        }

        let payload: [String: Any] = [
            "origin": expectedOrigin,
            "access": access,
            "refresh": refresh,
            "overwrite": handoff.overwriteLocalStorage,
            "nonce": handoff.nonce,
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: payload, options: [.withoutEscapingSlashes]),
              let json = String(data: data, encoding: .utf8) else {
            return nil
        }

        return """
        (function(cfg) {
          try {
            if (window.location.origin !== cfg.origin) return;
            var flag = '__cc_native_handoff_' + cfg.nonce;
            if (window.sessionStorage && window.sessionStorage.getItem(flag)) return;
            var hasExisting = !!(window.localStorage.getItem('claude_tunnel_token') || window.localStorage.getItem('claude_refresh_token'));
            if (cfg.overwrite || !hasExisting) {
              if (cfg.access) window.localStorage.setItem('claude_tunnel_token', cfg.access);
              if (cfg.refresh) window.localStorage.setItem('claude_refresh_token', cfg.refresh);
            }
            if (window.sessionStorage) window.sessionStorage.setItem(flag, '1');
          } catch (_) {}
        })(\(json));
        """
    }
}

@MainActor
final class AppSessionStore: ObservableObject {
    @Published private(set) var computer: Computer?
    @Published private(set) var isAuthenticated: Bool = false

    var onDiscoveredComputerName: ((UUID, String) -> Void)?

    private(set) var api: CarnivoreAPI?
    private var pendingHandoff: WebAuthHandoff?

    func select(computer: Computer?) {
        self.computer = computer
        guard let computer else {
            api = nil
            isAuthenticated = false
            pendingHandoff = nil
            return
        }

        let client = CarnivoreAPI(computer: computer)
        self.api = client

        if let creds = AuthKeychain.load(origin: computer.origin.pushId), creds.hasTokens {
            pendingHandoff = WebAuthHandoff(
                originId: computer.origin.pushId,
                credentials: creds,
                overwriteLocalStorage: false
            )
            isAuthenticated = true
        } else {
            pendingHandoff = nil
            isAuthenticated = false
        }
    }

    func didAuthenticate() async {
        guard let computer else { return }
        if let creds = AuthKeychain.load(origin: computer.origin.pushId) {
            pendingHandoff = WebAuthHandoff(
                originId: computer.origin.pushId,
                credentials: creds,
                overwriteLocalStorage: true
            )
        }
        isAuthenticated = true

        if computer.isRawRelayHashName, let api {
            Task { [weak self] in
                guard let activity = try? await api.fetchPackActivity(),
                      let label = activity.selfComputerLabel else { return }
                self?.onDiscoveredComputerName?(computer.id, label)
            }
        }
    }

    func consumeWebAuthHandoff(for originId: String) -> WebAuthHandoff? {
        guard let handoff = pendingHandoff, handoff.originId == originId else { return nil }
        pendingHandoff = nil
        return handoff
    }

    func signOut() async {
        pendingHandoff = nil
        await api?.signOut()
        if let computer {
            let store = WKWebsiteDataStore(forIdentifier: computer.id)
            await store.removeData(ofTypes: WKWebsiteDataStore.allWebsiteDataTypes(), modifiedSince: .distantPast)
        }
        isAuthenticated = false
    }
}
