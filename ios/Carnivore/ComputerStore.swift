import Foundation

final class ComputerStore: ObservableObject {
    static let appGroup = "group.ai.carnivore"
    private static let key = "computers.v1"

    @Published private(set) var computers: [Computer] = []
    private let defaults: UserDefaults

    init(defaults: UserDefaults? = UserDefaults(suiteName: ComputerStore.appGroup)) {
        self.defaults = defaults ?? .standard
        if let data = self.defaults.data(forKey: Self.key),
           let saved = try? JSONDecoder().decode([Computer].self, from: data) {
            computers = saved
        }
    }

    func add(_ computer: Computer) {
        computers.append(computer)
        save()
    }

    func remove(at offsets: IndexSet) {
        let removed = offsets.map { computers[$0] }
        computers.remove(atOffsets: offsets)
        save()
        for gone in removed where !computers.contains(where: { $0.origin == gone.origin }) {
            PushKeyStore.remove(origin: gone.origin.pushId)
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
}
