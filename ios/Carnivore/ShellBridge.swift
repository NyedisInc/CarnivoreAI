import Combine
import Foundation
import WebKit

@MainActor
final class ShellBridge: NSObject, WKScriptMessageHandler {
    static let handlerName = "carnivore"
    static let version = 1
    private(set) static var viewing: (origin: String, session: String)? = nil
    private weak var webView: WKWebView?
    private let origin: Origin
    private let computer: Computer
    let canPush: Bool
    var originPushId: String { origin.pushId }
    private var ready = false
    private var tapWatch: AnyCancellable?
    private var dictation: SpeechDictation?

    init(computer: Computer) {
        self.origin = computer.origin
        self.computer = computer
        self.canPush = computer.kind == .relay && computer.origin.isEncrypted
        super.init()
    }

    func install(on config: WKWebViewConfiguration) {
        let script = WKUserScript(
            source: "window.carnivoreShell = { version: \(Self.version), platform: 'ios', speech: true };",
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
        Self.viewing = nil
        dictation?.cancel()
        dictation = nil
        view.configuration.userContentController.removeScriptMessageHandler(forName: Self.handlerName)
        tapWatch = nil
        if PushRegistrar.shared.bridge === self { PushRegistrar.shared.bridge = nil }
    }

    private func trusted(_ message: WKScriptMessage) -> Bool {
        let o = message.frameInfo.securityOrigin
        return message.frameInfo.isMainFrame
            && Self.sameOrigin(scheme: o.protocol, host: o.host, port: o.port, as: origin)
    }

    nonisolated static func sameOrigin(scheme: String, host: String, port: Int, as origin: Origin) -> Bool {
        let scheme = scheme.lowercased()
        let effective = port == 0 ? (scheme == "https" ? 443 : 80) : port
        let cleanHost = host.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: "[]"))
        return cleanHost == origin.host && scheme == origin.scheme && effective == origin.port
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
        case "viewing":
            if let session = body["session"] as? String, session.count <= 200 {
                Self.viewing = session.isEmpty ? nil : (origin.pushId, session)
            }
        case "statusKey":
            if computer.kind == .relay, let token = body["token"] as? String {
                StatusKeyStore.set(token, origin: origin.pushId)
            }
        case "speechStart":
            ensureDictation().start()
        case "speechStop":
            dictation?.stop()
        case "speechCancel":
            dictation?.cancel()
        default:
            break
        }
    }

    private func ensureDictation() -> SpeechDictation {
        if let existing = dictation { return existing }
        let created = SpeechDictation { [weak self] msg in self?.send(msg) }
        dictation = created
        return created
    }

    nonisolated static func reportTheme(_ id: String) {
        Task { @MainActor in ThemeStore.shared.report(id: id) }
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
