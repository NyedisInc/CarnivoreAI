import Photos
import UIKit
import UserNotifications

enum NotifyActions {
    static func handle(_ response: UNNotificationResponse) async {
        let id = response.actionIdentifier
        let userInfo = response.notification.request.content.userInfo
        guard id != UNNotificationDefaultActionIdentifier, id != UNNotificationDismissActionIdentifier,
              let info = NotifyUserInfo(userInfo: userInfo) else { return }
        let card = NotifyCard(json: info.cardJSON)
        switch id {
        case "open_link":
            if let url = card.string("url").flatMap(URL.init(string:)), url.scheme == "https" { await UIApplication.shared.open(url) }
        case "save":
            await saveImage(info)
        case "save_file":
            await exportFile(info, name: card.string("name") ?? "file")
        case "later", "copy_link":
            break
        default:
            if NotifyCategories.contractAction(kind: info.kind, id: id)?.foreground == true {
                TapRouter.shared.tapped(userInfo: userInfo)
                return
            }
            guard let base = info.base, let cap = info.cap else { return await notSent() }
            let typed = (response as? UNTextInputNotificationResponse)?.userText
            let outcome = await AnswerClient.act(base: base, cap: cap, action: id, text: typed)
            if case .sent = outcome { return }
            await notSent()
        }
    }

    private static func notSent() async {
        let content = UNMutableNotificationContent()
        content.title = Strings.notifyNotSent
        try? await UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil))
    }

    private static func saveImage(_ info: NotifyUserInfo) async {
        guard let base = info.base, let cap = info.cap, let media = info.media,
              let data = await AnswerClient.fetchMedia(base: base, cap: cap, id: media.id, poster: false),
              let image = UIImage(data: data) else { return await notSent() }
        UIImageWriteToSavedPhotosAlbum(image, nil, nil, nil)
    }

    @MainActor private static func exportFile(_ info: NotifyUserInfo, name: String) async {
        guard let base = info.base, let cap = info.cap, let media = info.media,
              let data = await AnswerClient.fetchMedia(base: base, cap: cap, id: media.id, poster: false) else { return await notSent() }
        let url = FileManager.default.temporaryDirectory.appendingPathComponent(name.replacingOccurrences(of: "/", with: "_"))
        guard (try? data.write(to: url, options: .completeFileProtection)) != nil,
              let root = UIApplication.shared.connectedScenes.compactMap({ ($0 as? UIWindowScene)?.keyWindow?.rootViewController }).first else { return await notSent() }
        root.present(UIDocumentPickerViewController(forExporting: [url]), animated: true)
    }
}
