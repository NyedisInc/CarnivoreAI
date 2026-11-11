import SwiftUI
import UIKit
import UserNotifications
import UserNotificationsUI

final class NotificationViewController: UIViewController, UNNotificationContentExtension {
    private let state = CardState()
    private var host: UIHostingController<CardHost>?

    override func viewDidLoad() {
        super.viewDidLoad()
        let controller = UIHostingController(rootView: CardHost(state: state))
        addChild(controller)
        controller.view.translatesAutoresizingMaskIntoConstraints = false
        controller.view.backgroundColor = .clear
        view.addSubview(controller.view)
        NSLayoutConstraint.activate([
            controller.view.topAnchor.constraint(equalTo: view.topAnchor), controller.view.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            controller.view.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            controller.view.bottomAnchor.constraint(equalTo: view.bottomAnchor),
        ])
        controller.didMove(toParent: self)
        host = controller
    }

    func didReceive(_ notification: UNNotification) {
        state.load(content: notification.request.content)
        if let info = state.info {
            extensionContext?.notificationActions = NotifyCategories.actions(kind: info.kind, acts: info.acts)
        }
        fit()
        DispatchQueue.main.async { [weak self] in self?.fit() }
    }

    private func fit() {
        guard let host else { return }
        host.view.layoutIfNeeded()
        let size = host.sizeThatFits(in: CGSize(width: view.bounds.width, height: .greatestFiniteMagnitude))
        preferredContentSize = CGSize(width: view.bounds.width, height: size.height)
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        fit()
    }

    func didReceive(_ response: UNNotificationResponse, completionHandler completion: @escaping (UNNotificationContentExtensionResponseOption) -> Void) {
        let id = response.actionIdentifier
        if id == UNNotificationDefaultActionIdentifier || id == UNNotificationDismissActionIdentifier { return completion(.dismissAndForwardAction) }
        if let kind = state.info?.kind, NotifyCategories.contractAction(kind: kind, id: id)?.foreground == true { return completion(.dismissAndForwardAction) }
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
