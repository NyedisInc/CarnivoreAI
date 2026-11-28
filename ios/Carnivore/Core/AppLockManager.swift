import LocalAuthentication
import SwiftUI

enum AppLockTimeout: Int, CaseIterable, Identifiable, Sendable {
    case immediate = 0
    case oneMinute = 60
    case fiveMinutes = 300

    var id: Int { rawValue }

    var label: String {
        switch self {
        case .immediate: return "Immediately"
        case .oneMinute: return "After 1 min"
        case .fiveMinutes: return "After 5 min"
        }
    }
}

@MainActor
final class AppLockManager: ObservableObject {
    private static let enabledKey = "security.applock.enabled.v1"
    private static let timeoutKey = "security.applock.timeout.v1"

    @Published var isEnabled: Bool {
        didSet {
            defaults.set(isEnabled, forKey: Self.enabledKey)
            if !isEnabled { isLocked = false }
        }
    }

    @Published var timeout: AppLockTimeout {
        didSet {
            defaults.set(timeout.rawValue, forKey: Self.timeoutKey)
        }
    }

    @Published private(set) var isLocked: Bool = false
    @Published private(set) var isAuthenticating: Bool = false
    @Published private(set) var lastError: String?

    private let defaults: UserDefaults
    private var backgroundedAt: Date?

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        let runningTests = ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil
        let enabled = defaults.object(forKey: Self.enabledKey) as? Bool ?? true
        let rawTimeout = defaults.object(forKey: Self.timeoutKey) as? Int ?? AppLockTimeout.immediate.rawValue
        self.isEnabled = enabled
        self.timeout = AppLockTimeout(rawValue: rawTimeout) ?? .immediate
        self.isLocked = enabled && !runningTests
    }

    var biometricLabel: String {
        let context = LAContext()
        var err: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &err) else {
            return "Passcode"
        }
        switch context.biometryType {
        case .faceID: return "Face ID"
        case .touchID: return "Touch ID"
        case .opticID: return "Optic ID"
        default: return "Passcode"
        }
    }

    var biometricIcon: String {
        let context = LAContext()
        var err: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &err) else {
            return "lock.fill"
        }
        switch context.biometryType {
        case .faceID: return "faceid"
        case .touchID: return "touchid"
        case .opticID: return "opticid"
        default: return "lock.fill"
        }
    }

    func handleScenePhase(_ phase: ScenePhase) {
        switch phase {
        case .background:
            backgroundedAt = Date()
            if isEnabled && timeout == .immediate {
                isLocked = true
            }
        case .active:
            guard isEnabled else {
                isLocked = false
                return
            }
            if let left = backgroundedAt {
                backgroundedAt = nil
                if Date().timeIntervalSince(left) >= TimeInterval(timeout.rawValue) {
                    isLocked = true
                }
            }
            if isLocked {
                Task { await unlock() }
            }
        case .inactive:
            break
        @unknown default:
            break
        }
    }

    func lockNow() {
        guard isEnabled else { return }
        isLocked = true
    }

    func unlock() async {
        guard isEnabled else {
            isLocked = false
            return
        }
        guard !isAuthenticating else { return }
        isAuthenticating = true
        lastError = nil
        defer { isAuthenticating = false }

        let context = LAContext()
        context.localizedCancelTitle = "Cancel"
        var error: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
            #if targetEnvironment(simulator)
            isLocked = false
            return
            #else
            lastError = error?.localizedDescription ?? "Device passcode not configured."
            return
            #endif
        }
        do {
            let ok = try await context.evaluatePolicy(
                .deviceOwnerAuthentication,
                localizedReason: "Unlock Carnivore terminal sessions and approvals"
            )
            if ok {
                Haptics.success()
                isLocked = false
            }
        } catch {
            Haptics.error()
            lastError = "Authentication cancelled or failed."
        }
    }
}

struct PrivacyShieldView: View {
    let locked: Bool
    let biometricLabel: String
    let biometricIcon: String
    let error: String?
    let onUnlock: () -> Void
    @EnvironmentObject private var theme: ThemeStore

    var body: some View {
        let p = theme.palette
        ZStack {
            p.page.ignoresSafeArea()
            VStack(spacing: 0) {
                HStack {
                    Image("CarnivoreWordmark")
                        .resizable()
                        .interpolation(.high)
                        .scaledToFit()
                        .frame(height: 20)
                    Spacer()
                    Text(locked ? "LOCKED" : "PROTECTED")
                        .font(.system(size: 11, weight: .semibold, design: .monospaced))
                        .tracking(1.4)
                        .foregroundStyle(p.accent)
                }
                .padding(.horizontal, 14)
                .frame(height: 40)
                .background(p.ground)

                Rectangle().fill(p.line).frame(height: 1)

                VStack(spacing: 18) {
                    Image("CarnivoreMark")
                        .resizable()
                        .interpolation(.high)
                        .scaledToFit()
                        .frame(width: 44, height: 44)
                        .padding(.top, 8)

                    Text(locked ? "Session locked on this device." : "Session hidden while inactive.")
                        .font(.system(size: 12, design: .monospaced))
                        .foregroundStyle(p.textMuted)
                        .multilineTextAlignment(.center)

                    if locked {
                        Button(action: onUnlock) {
                            HStack(spacing: 8) {
                                Image(systemName: biometricIcon)
                                    .font(.system(size: 14, weight: .medium))
                                Text(Strings.fill(Strings.appUnlockWith, ["label": biometricLabel]))
                                    .font(.system(size: 13, weight: .semibold, design: .monospaced))
                            }
                            .foregroundStyle(p.success)
                            .frame(maxWidth: .infinity)
                            .frame(minHeight: 44)
                            .background(p.success.opacity(0.12))
                            .overlay(RoundedRectangle(cornerRadius: 2).stroke(p.success, lineWidth: 1))
                        }
                        .buttonStyle(.plain)
                    }

                    if let error {
                        Text(error)
                            .font(.system(size: 12, design: .monospaced))
                            .foregroundStyle(p.danger)
                            .multilineTextAlignment(.center)
                            .padding(8)
                            .frame(maxWidth: .infinity)
                            .overlay(RoundedRectangle(cornerRadius: 2).stroke(p.danger, lineWidth: 1))
                    }
                }
                .padding(16)
            }
            .frame(maxWidth: 360)
            .background(p.card)
            .overlay(RoundedRectangle(cornerRadius: 2).stroke(p.line, lineWidth: 1))
            .padding(.horizontal, 20)
        }
    }
}
