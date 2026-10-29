import Combine
import Foundation
import WebKit

final class ShellBridge: NSObject, WKScriptMessageHandler {
    static let handlerName = "carnivore"
    static let version = 1
    private weak var webView: WKWebView?
    private let origin: Origin
    let canPush: Bool
    private var ready = false
    private var tapWatch: AnyCancellable?

    init(computer: Computer) {
        self.origin = computer.origin
        self.canPush = computer.kind == .relay && computer.origin.isEncrypted
        super.init()
    }

    func install(on config: WKWebViewConfiguration) {
        let script = WKUserScript(
            source: "window.carnivoreShell = { version: \(Self.version), platform: 'ios' };",
            injectionTime: .atDocumentStart, forMainFrameOnly: true)
        config.userContentController.addUserScript(script)
        config.userContentController.add(self, name: Self.handlerName)
    }

    func attach(_ view: WKWebView) {
        webView = view
        PushRegistrar.shared.bridge = self
        tapWatch = TapRouter.shared.$pending.receive(on: DispatchQueue.main).sink { [weak self] _ in self?.flushTap() }
    }

    func detach(_ view: WKWebView) {
        view.configuration.userContentController.removeScriptMessageHandler(forName: Self.handlerName)
        tapWatch = nil
        if PushRegistrar.shared.bridge === self { PushRegistrar.shared.bridge = nil }
    }

    private func trusted(_ message: WKScriptMessage) -> Bool {
        let o = message.frameInfo.securityOrigin
        return message.frameInfo.isMainFrame
            && Self.sameOrigin(scheme: o.protocol, host: o.host, port: o.port, as: origin)
    }

    static func sameOrigin(scheme: String, host: String, port: Int, as origin: Origin) -> Bool {
        let scheme = scheme.lowercased()
        let effective = port == 0 ? (scheme == "https" ? 443 : 80) : port
        return host.lowercased() == origin.host && scheme == origin.scheme && effective == origin.port
    }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard trusted(message), let body = message.body as? [String: Any],
              (body["v"] as? Int) == Self.version, let type = body["type"] as? String else { return }
        switch type {
        case "ready":
            ready = true
            flushTap()
            if canPush, PushKeyStore.needsReregistration(origin: origin.pushId) {
                PushRegistrar.shared.start(origin: origin.pushId)
            }
        case "registerPush":
            if canPush { PushRegistrar.shared.start(origin: origin.pushId) }
            else { send(["type": "pushFailed", "reason": "unsupported"]) }
        case "pushRegistered":
            if canPush, let id = body["id"] as? String { PushKeyStore.setRowId(id, origin: origin.pushId) }
        case "theme":
            if let id = body["id"] as? String { Self.reportTheme(id) }
        default:
            break
        }
    }

    static func reportTheme(_ id: String) {
        DispatchQueue.main.async { ThemeStore.shared.report(id: id) }
    }

    private func flushTap() {
        guard ready, let path = TapRouter.shared.take(forOrigin: origin.pushId) else { return }
        send(["type": "openPath", "path": path])
    }

    func send(_ fields: [String: String]) {
        var message: [String: Any] = fields
        message["v"] = Self.version
        guard let data = try? JSONSerialization.data(withJSONObject: message),
              let json = String(data: data, encoding: .utf8) else { return }
        webView?.evaluateJavaScript("window.carnivoreShell && window.carnivoreShell.receive && window.carnivoreShell.receive(\(json))")
    }
}
