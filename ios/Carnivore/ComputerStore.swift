import Foundation
import WebKit

@MainActor
final class ComputerStore: ObservableObject {
    static let appGroup = "group.ai.carnivore"
    private static let key = "computers.v1"
    private static let activeKey = "computers.active.v1"
    private static let installSentinelKey = "carnivore.installed.v2"

    @Published private(set) var computers: [Computer] = []
    @Published var activeComputerId: UUID? {
        didSet {
            if let id = activeComputerId {
                defaults.set(id.uuidString, forKey: Self.activeKey)
            } else {
                defaults.removeObject(forKey: Self.activeKey)
            }
        }
    }

    private let defaults: UserDefaults

    init(defaults: UserDefaults? = UserDefaults(suiteName: ComputerStore.appGroup), checkFreshInstall: Bool = true) {
        self.defaults = defaults ?? .standard
        if checkFreshInstall {
            Self.wipeKeychainIfFreshInstall(defaults: self.defaults)
        }
        if let data = self.defaults.data(forKey: Self.key),
           let saved = try? JSONDecoder().decode([Computer].self, from: data) {
            computers = saved
        }
        if let rawId = self.defaults.string(forKey: Self.activeKey),
           let uuid = UUID(uuidString: rawId),
           computers.contains(where: { $0.id == uuid }) {
            activeComputerId = uuid
        } else {
            activeComputerId = computers.first?.id
        }
    }

    var activeComputer: Computer? {
        if let id = activeComputerId, let hit = computers.first(where: { $0.id == id }) {
            return hit
        }
        return computers.first
    }

    @discardableResult
    func add(_ computer: Computer) -> Computer {
        if let idx = computers.firstIndex(where: { $0.origin == computer.origin }) {
            var updated = computers[idx]
            if !computer.name.isEmpty { updated.name = computer.name }
            updated.kind = computer.kind
            computers[idx] = updated
            activeComputerId = updated.id
            save()
            return updated
        }
        computers.append(computer)
        activeComputerId = computer.id
        save()
        return computer
    }

    func rename(id: UUID, to newName: String) {
        let trimmed = newName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, let idx = computers.firstIndex(where: { $0.id == id }) else { return }
        computers[idx].name = trimmed
        save()
    }

    func remove(at offsets: IndexSet) {
        let removed = offsets.map { computers[$0] }
        computers.remove(atOffsets: offsets)
        if let active = activeComputerId, !computers.contains(where: { $0.id == active }) {
            activeComputerId = computers.first?.id
        }
        save()
        for gone in removed {
            purgeComputerData(gone)
        }
    }

    func remove(id: UUID) {
        guard let idx = computers.firstIndex(where: { $0.id == id }) else { return }
        remove(at: IndexSet(integer: idx))
    }

    private func purgeComputerData(_ gone: Computer) {
        if !computers.contains(where: { $0.origin == gone.origin }) {
            PushKeyStore.remove(origin: gone.origin.pushId)
            StatusKeyStore.remove(origin: gone.origin.pushId)
            AuthKeychain.remove(origin: gone.origin.pushId)
        }
        let storeId = gone.id
        Task {
            try? await WKWebsiteDataStore.remove(forIdentifier: storeId)
        }
    }

    func computer(forOrigin id: String) -> Computer? {
        computers.first { $0.origin.pushId == id }
    }

    private func save() {
        do {
            defaults.set(try JSONEncoder().encode(computers), forKey: Self.key)
        } catch {
            NSLog("carnivore: could not save computers: \(error)")
        }
    }

    private static func wipeKeychainIfFreshInstall(defaults: UserDefaults) {
        let standard = UserDefaults.standard
        if !standard.bool(forKey: installSentinelKey) {
            if defaults.data(forKey: key) == nil {
                AuthKeychain.removeAll()
                PushKeyStore.removeAll()
            }
            standard.set(true, forKey: installSentinelKey)
        }
    }
}
