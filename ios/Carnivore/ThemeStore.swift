import SwiftUI

final class ThemeStore: ObservableObject {
    static let key = "themeId"
    static let shared = ThemeStore()

    @Published private(set) var palette: Palette

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        palette = Palettes.palette(id: defaults.string(forKey: Self.key))
    }

    private let defaults: UserDefaults

    func report(id: String) {
        defaults.set(id, forKey: Self.key)
        palette = Palettes.palette(id: id)
    }
}
