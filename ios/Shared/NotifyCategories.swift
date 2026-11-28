import UserNotifications

enum NotifyCategories {
    private static let lockScreenProtectedIds: Set<String> = ["copy_link", "play"]

    static func label(_ key: String) -> String {
        switch key {
        case "notify.card.act.yes": return Strings.cardActYes
        case "notify.card.act.no": return Strings.cardActNo
        case "notify.card.act.reply": return Strings.cardActReply
        case "notify.card.act.opt.1": return Strings.cardActOpt1
        case "notify.card.act.opt.2": return Strings.cardActOpt2
        case "notify.card.act.opt.3": return Strings.cardActOpt3
        case "notify.card.act.opt.4": return Strings.cardActOpt4
        case "notify.card.act.open_file": return Strings.cardActOpenFile
        case "notify.card.act.save_file": return Strings.cardActSaveFile
        case "notify.card.act.open_link": return Strings.cardActOpenLink
        case "notify.card.act.copy_link": return Strings.cardActCopyLink
        case "notify.card.act.open": return Strings.cardActOpen
        case "notify.card.act.save": return Strings.cardActSave
        case "notify.card.act.play": return Strings.cardActPlay
        case "notify.card.act.reopen": return Strings.cardActReopen
        case "notify.card.act.restart_agents": return Strings.cardActRestartAgents
        case "notify.card.act.later": return Strings.cardActLater
        case "notify.card.act.install": return Strings.cardActInstall
        case "notify.card.act.pick.1": return Strings.cardActPick1
        case "notify.card.act.pick.2": return Strings.cardActPick2
        case "notify.card.act.answer": return Strings.cardActAnswer
        case "notify.card.act.sign_in": return Strings.cardActSignIn
        default: return key
        }
    }

    static func action(_ a: NotifyAction, title: String) -> UNNotificationAction {
        var options: UNNotificationActionOptions = []
        if a.faceId || lockScreenProtectedIds.contains(a.id) { options.insert(.authenticationRequired) }
        if a.foreground { options.insert(.foreground) }
        if a.textInput {
            return UNTextInputNotificationAction(identifier: a.id, title: title, options: options,
                                                 textInputButtonTitle: Strings.cardActReply, textInputPlaceholder: Strings.cardReplyPlaceholder)
        }
        return UNNotificationAction(identifier: a.id, title: title, options: options)
    }

    static func contractAction(kind: NotifyKind, id: String) -> NotifyAction? {
        let list = NotifyContract.actions[kind] ?? []
        if let hit = list.first(where: { $0.id == id }) { return hit }
        if id.hasPrefix("opt."), let first = list.first(where: { $0.id == "opt.1" }) {
            return NotifyAction(id: id, labelKey: first.labelKey, faceId: first.faceId, textInput: false, foreground: false)
        }
        return nil
    }

    static func actions(kind: NotifyKind, acts: [[String]]) -> [UNNotificationAction] {
        if acts.isEmpty { return (NotifyContract.actions[kind] ?? []).map { action($0, title: label($0.labelKey)) } }
        return acts.compactMap { pair in
            guard pair.count >= 2 else { return nil }
            return contractAction(kind: kind, id: pair[0]).map { action($0, title: pair[1]) }
        }
    }

    static func all() -> Set<UNNotificationCategory> {
        Set(NotifyKind.allCases.map { kind in
            UNNotificationCategory(identifier: NotifyContract.categoryId(kind), actions: actions(kind: kind, acts: []), intentIdentifiers: [], options: [])
        })
    }
}
