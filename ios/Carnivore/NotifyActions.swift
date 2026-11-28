import Photos
import UIKit
import UniformTypeIdentifiers
import UserNotifications

enum NotifyActions {
    @MainActor
    static func handle(_ response: UNNotificationResponse) async {
        let id = response.actionIdentifier
        let userInfo = response.notification.request.content.userInfo
        guard id != UNNotificationDefaultActionIdentifier,
              id != UNNotificationDismissActionIdentifier,
              let info = NotifyUserInfo(userInfo: userInfo, requireValidMAC: true) else { return }
        let card = NotifyCard(json: info.cardJSON)
        switch id {
        case "open_link":
            if let url = card.string("url").flatMap(URL.init(string:)), url.scheme?.lowercased() == "https" {
                await UIApplication.shared.open(url)
            }
        case "copy_link":
            if let url = card.string("url"), !url.isEmpty {
                UIPasteboard.general.setItems(
                    [[UTType.plainText.identifier: url]],
                    options: [.localOnly: true, .expirationDate: Date().addingTimeInterval(60)]
                )
            }
        case "play":
            TapRouter.shared.tapped(userInfo: userInfo, requireValidMAC: true)
        case "save":
            await saveImage(info)
        case "save_file":
            await exportFile(info, name: card.string("name") ?? "file")
        case "later":
            break
        default:
            if NotifyCategories.contractAction(kind: info.kind, id: id)?.foreground == true {
                TapRouter.shared.tapped(userInfo: userInfo, requireValidMAC: true)
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
        try? await UNUserNotificationCenter.current().add(
            UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        )
    }

    private static func saveImage(_ info: NotifyUserInfo) async {
        guard let base = info.base, let cap = info.cap, let media = info.media,
              let data = await AnswerClient.fetchMedia(base: base, cap: cap, id: media.id, poster: false),
              let image = UIImage(data: data) else { return await notSent() }
        let auth = await PHPhotoLibrary.requestAuthorization(for: .addOnly)
        guard auth == .authorized || auth == .limited else { return await notSent() }
        do {
            try await PHPhotoLibrary.shared().performChanges {
                PHAssetChangeRequest.creationRequestForAsset(from: image)
            }
        } catch {
            await notSent()
        }
    }

    static func safeFilename(_ raw: String) -> String {
        let base = URL(fileURLWithPath: raw).lastPathComponent
        let cleaned = base.unicodeScalars.map { scalar -> Character in
            let v = scalar.value
            if v < 32 || v == 127 || scalar == "/" || scalar == ":" || scalar == "\\" { return "_" }
            return Character(scalar)
        }
        let result = String(cleaned).trimmingCharacters(in: CharacterSet(charactersIn: ". "))
        return result.isEmpty ? "file" : String(result.prefix(120))
    }

    @MainActor private static func exportFile(_ info: NotifyUserInfo, name: String) async {
        guard let base = info.base, let cap = info.cap, let media = info.media,
              let data = await AnswerClient.fetchMedia(base: base, cap: cap, id: media.id, poster: false) else { return await notSent() }
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("export-\(UUID().uuidString)", isDirectory: true)
        guard (try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])) != nil else {
            return await notSent()
        }
        let url = dir.appendingPathComponent(safeFilename(name))
        guard (try? data.write(to: url, options: [.atomic, .completeFileProtection])) != nil,
              let presenter = topViewController() else {
            try? FileManager.default.removeItem(at: dir)
            return await notSent()
        }
        let picker = UIDocumentPickerViewController(forExporting: [url], asCopy: true)
        presenter.present(picker, animated: true) {
            DispatchQueue.main.asyncAfter(deadline: .now() + 60) {
                try? FileManager.default.removeItem(at: dir)
            }
        }
    }

    @MainActor private static func topViewController() -> UIViewController? {
        let root = UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .flatMap(\.windows)
            .first(where: \.isKeyWindow)?
            .rootViewController
        var current = root
        while let next = current?.presentedViewController {
            current = next
        }
        return current
    }
}
