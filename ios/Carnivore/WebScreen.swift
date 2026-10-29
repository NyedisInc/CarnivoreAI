import SwiftUI
import WebKit

struct WebScreen: View {
    let computer: Computer
    var startURL: URL?
    let close: () -> Void
    @State private var version: VersionStatus?
    @State private var failure: UnreachableReason?
    @State private var reloadToken = 0
    @EnvironmentObject private var theme: ThemeStore

    private var blocking: UnreachableReason? {
        if let failure { return failure }
        if case .serverTooOld(let server, let needs)? = version {
            return .versionMismatch(server: server, needs: needs)
        }
        return nil
    }

    var body: some View {
        ZStack {
            WebView(computer: computer, startURL: startURL, reloadToken: reloadToken) {
                failure = UnreachableReason.classify($0, kind: computer.kind)
            }
            .ignoresSafeArea(edges: .bottom)
            if let reason = blocking {
                UnreachableView(computer: computer, reason: reason, retry: retry, close: close)
            }
        }
        .background(theme.palette.page)
        .task { version = await VersionCheck.fetch(origin: computer.origin) }
    }

    private func retry() {
        failure = nil
        version = nil
        reloadToken += 1
        Task { version = await VersionCheck.fetch(origin: computer.origin) }
    }
}

struct WebView: UIViewRepresentable {
    let computer: Computer
    private var origin: Origin { computer.origin }
    let startURL: URL?
    let reloadToken: Int
    let onFailure: (Error) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(computer: computer, onFailure: onFailure) }

    static func dismantleUIView(_ view: WKWebView, coordinator: Coordinator) { coordinator.bridge.detach(view) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        context.coordinator.bridge.install(on: config)
        let view = WKWebView(frame: .zero, configuration: config)
        view.navigationDelegate = context.coordinator
        view.uiDelegate = context.coordinator
        context.coordinator.bridge.attach(view)
        view.isOpaque = false
        view.backgroundColor = .black
        view.load(URLRequest(url: startURL ?? origin.rootURL))
        context.coordinator.lastReload = reloadToken
        return view
    }

    func updateUIView(_ view: WKWebView, context: Context) {
        if context.coordinator.lastReload != reloadToken {
            context.coordinator.lastReload = reloadToken
            view.load(URLRequest(url: startURL ?? origin.rootURL))
        }
    }

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
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard action.targetFrame?.isMainFrame ?? true, let url = action.request.url else {
                decisionHandler(.allow)
                return
            }
            switch OriginLock.decide(url, lockedTo: origin) {
            case .allow: decisionHandler(.allow)
            case .openInSafari:
                decisionHandler(.cancel)
                UIApplication.shared.open(url)
            case .block: decisionHandler(.cancel)
            }
        }

        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                     for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            guard let url = action.request.url else { return nil }
            switch OriginLock.decide(url, lockedTo: origin) {
            case .allow: webView.load(URLRequest(url: url))
            case .openInSafari: UIApplication.shared.open(url)
            case .block: break
            }
            return nil
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
                     withError error: Error) {
            onFailure(error)
        }
    }
}
