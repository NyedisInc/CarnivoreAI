import UIKit

@MainActor
enum Haptics {
    private static let selectionGenerator = UISelectionFeedbackGenerator()
    private static let lightGenerator = UIImpactFeedbackGenerator(style: .light)
    private static let mediumGenerator = UIImpactFeedbackGenerator(style: .medium)
    private static let heavyGenerator = UIImpactFeedbackGenerator(style: .heavy)
    private static let notificationGenerator = UINotificationFeedbackGenerator()

    static func selection() {
        selectionGenerator.selectionChanged()
    }

    static func tap() {
        lightGenerator.impactOccurred(intensity: 0.7)
    }

    static func key() {
        lightGenerator.impactOccurred(intensity: 0.55)
    }

    static func action() {
        mediumGenerator.impactOccurred()
    }

    static func destructive() {
        heavyGenerator.impactOccurred()
    }

    static func success() {
        notificationGenerator.notificationOccurred(.success)
    }

    static func warning() {
        notificationGenerator.notificationOccurred(.warning)
    }

    static func error() {
        notificationGenerator.notificationOccurred(.error)
    }
}
