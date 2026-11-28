import SwiftUI
import UIKit
@preconcurrency import UserNotifications
@preconcurrency import UserNotificationsUI

final class NotificationViewController: UIViewController, @preconcurrency UNNotificationContentExtension {
    private let state = CardState()
    private var host: UIHostingController<CardHost>?
    private var lastFittedSize: CGSize = .zero

    override func viewDidLoad() {
        super.viewDidLoad()
        let controller = UIHostingController(rootView: CardHost(state: state))
        addChild(controller)
        controller.view.translatesAutoresizingMaskIntoConstraints = false
        controller.view.backgroundColor = .clear
        view.addSubview(controller.view)
        NSLayoutConstraint.activate([
            controller.view.topAnchor.constraint(equalTo: view.topAnchor),
            controller.view.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            controller.view.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            controller.view.bottomAnchor.constraint(equalTo: view.bottomAnchor),
        ])
        controller.didMove(toParent: self)
        host = controller
    }

    func didReceive(_ notification: UNNotification) {
        state.load(content: notification.request.content, requireValidMAC: true)
        if let info = state.info {
            extensionContext?.notificationActions = NotifyCategories.actions(kind: info.kind, acts: info.acts)
        } else {
            extensionContext?.notificationActions = []
        }
        fit()
        DispatchQueue.main.async { [weak self] in self?.fit() }
    }

    private func fit() {
        guard let host else { return }
        let width = view.bounds.width
        guard width > 0 else { return }
        host.view.layoutIfNeeded()
        let measured = host.sizeThatFits(in: CGSize(width: width, height: .greatestFiniteMagnitude))
        let target = CGSize(width: width, height: max(44, ceil(measured.height)))
        if abs(target.width - lastFittedSize.width) > 0.5 || abs(target.height - lastFittedSize.height) > 0.5 {
            lastFittedSize = target
            preferredContentSize = target
        }
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        fit()
    }

    func didReceive(_ response: UNNotificationResponse, completionHandler completion: @escaping (UNNotificationContentExtensionResponseOption) -> Void) {
        let id = response.actionIdentifier
        if id == UNNotificationDefaultActionIdentifier || id == UNNotificationDismissActionIdentifier {
            return completion(.dismissAndForwardAction)
        }
        guard let info = state.info else { return completion(.dismiss) }
        if NotifyCategories.contractAction(kind: info.kind, id: id)?.foreground == true {
            return completion(.dismissAndForwardAction)
        }
        let typed = (response as? UNTextInputNotificationResponse)?.userText
        Task { @MainActor in
            let finished = await state.press(action: id, text: typed)
            fit()
            if finished {
                try? await Task.sleep(nanoseconds: 1_500_000_000)
                completion(.dismiss)
            } else {
                completion(.doNotDismiss)
            }
        }
    }
}

struct CardHost: View {
    @ObservedObject var state: CardState

    var body: some View {
        CardView(model: state.model, media: state.media, phase: state.phase)
    }
}
