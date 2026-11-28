import SwiftUI
import WebKit

struct WebScreen: View {
    let computer: Computer
    var sessionStore: AppSessionStore? = nil
    var startURL: URL?
    var externalReloadToken: Int = 0
    let close: () -> Void

    @State private var version: VersionStatus?
    @State private var failure: UnreachableReason?
    @State private var internalReloadToken = 0
    @EnvironmentObject private var theme: ThemeStore

    private var effectiveReloadToken: Int {
        externalReloadToken + internalReloadToken
    }

    private var blocking: UnreachableReason? {
        if let failure { return failure }
        if case .serverTooOld(let server, let needs)? = version {
            return .versionMismatch(server: server, needs: needs)
        }
        return nil
    }

    var body: some View {
        ZStack {
            WebView(
                computer: computer,
                sessionStore: sessionStore,
                startURL: startURL,
                reloadToken: effectiveReloadToken
            ) { error in
                let ns = error as NSError
                if ns.domain == NSURLErrorDomain && ns.code == NSURLErrorCancelled { return }
                if ns.domain == "WebKitErrorDomain" && ns.code == 102 { return }
                failure = UnreachableReason.classify(error, kind: computer.kind)
                if failure == .linkOffline { Task { await refineLinkOffline() } }
            }
            .ignoresSafeArea(edges: .bottom)

            if let reason = blocking {
                UnreachableView(computer: computer, reason: reason, retry: retry, close: close)
            }
        }
        .background(theme.palette.page)
        .task { version = await VersionCheck.fetch(origin: computer.origin) }
    }

    private func refineLinkOffline() async {
        let status = await LinkStatusClient.fetch(origin: computer.origin)
        if let current = failure { failure = current.refined(by: status) }
    }

    private func retry() {
        failure = nil
        version = nil
        internalReloadToken += 1
        Task { version = await VersionCheck.fetch(origin: computer.origin) }
    }
}

struct WebView: UIViewRepresentable {
    let computer: Computer
    var sessionStore: AppSessionStore?
    private var origin: Origin { computer.origin }
    let startURL: URL?
    let reloadToken: Int
    let onFailure: (Error) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(computer: computer, onFailure: onFailure) }

    static func dismantleUIView(_ view: WKWebView, coordinator: Coordinator) { coordinator.bridge.detach(view) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        let dataStore = WKWebsiteDataStore(forIdentifier: computer.id)
        config.websiteDataStore = dataStore
        config.allowsInlineMediaPlayback = true

        context.coordinator.bridge.install(on: config)

        let handoff = sessionStore?.consumeWebAuthHandoff(for: origin.pushId)
        if let handoff, let scriptSource = WebAuthHandoff.makeSeedScript(origin: origin, handoff: handoff) {
            let authScript = WKUserScript(source: scriptSource, injectionTime: .atDocumentStart, forMainFrameOnly: true)
            config.userContentController.addUserScript(authScript)
        }

        let view = WKWebView(frame: .zero, configuration: config)
        view.navigationDelegate = context.coordinator
        view.uiDelegate = context.coordinator
        context.coordinator.bridge.attach(view)
        view.isOpaque = false
        view.backgroundColor = .black

        let targetURL = startURL ?? origin.rootURL
        let rawLinkCookie = handoff?.credentials.linkCookie ?? AuthKeychain.load(origin: origin.pushId)?.linkCookie
        context.coordinator.lastReload = reloadToken

        if let cookie = WebAuthHandoff.makeLinkCookie(origin: origin, rawCookie: rawLinkCookie) {
            dataStore.httpCookieStore.setCookie(cookie) {
                DispatchQueue.main.async {
                    view.load(URLRequest(url: targetURL))
                }
            }
        } else {
            view.load(URLRequest(url: targetURL))
        }
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {
        if context.coordinator.lastReload != reloadToken {
            context.coordinator.lastReload = reloadToken
            view.load(URLRequest(url: startURL ?? origin.rootURL))
        }
    }

    @MainActor
    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate {
        let origin: Origin
        let onFailure: (Error) -> Void
        var lastReload = 0
        let bridge: ShellBridge

        init(computer: Computer, onFailure: @escaping (Error) -> Void) {
            self.origin = computer.origin
            self.onFailure = onFailure
            self.bridge = ShellBridge(computer: computer)
        }

        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                     decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void) {
            guard let url = action.request.url else {
                decisionHandler(.cancel)
                return
            }
            let isMain = action.targetFrame?.isMainFrame ?? true
            switch OriginLock.decide(url, lockedTo: origin) {
            case .allow:
                decisionHandler(.allow)
            case .openInSafari:
                decisionHandler(.cancel)
                if isMain && action.navigationType == .linkActivated {
                    UIApplication.shared.open(url)
                }
            case .block:
                decisionHandler(.cancel)
            }
        }

        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                     for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            guard let url = action.request.url else { return nil }
            switch OriginLock.decide(url, lockedTo: origin) {
            case .allow: webView.load(URLRequest(url: url))
            case .openInSafari:
                if action.navigationType == .linkActivated {
                    UIApplication.shared.open(url)
                }
            case .block: break
            }
            return nil
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
                     withError error: Error) {
            onFailure(error)
        }

        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
            webView.reload()
        }
    }
}
