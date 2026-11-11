import XCTest

final class NotifyShotsUITests: XCTestCase {
    private var dir = ""

    private func waitForFile(_ path: String, timeout: TimeInterval = 90) -> Bool {
        let end = Date().addingTimeInterval(timeout)
        while Date() < end {
            if FileManager.default.fileExists(atPath: path) { return true }
            Thread.sleep(forTimeInterval: 0.3)
        }
        return false
    }

    private func save(_ name: String) {
        let png = XCUIScreen.main.screenshot().pngRepresentation
        try? png.write(to: URL(fileURLWithPath: dir + "/" + name + ".png"))
    }

    func testBannerAndCardForEveryKind() throws {
        let env = ProcessInfo.processInfo.environment
        dir = try XCTUnwrap(env["NOTIFY_SHOTS_DIR"], "NOTIFY_SHOTS_DIR not set")
        let kinds = (env["NOTIFY_KINDS"] ?? "").split(separator: ",").map(String.init)
        try XCTSkipIf(kinds.isEmpty, "NOTIFY_KINDS not set")
        let origin = env["NOTIFY_ORIGIN"] ?? "http://127.0.0.1:5897"

        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let app = XCUIApplication()
        app.launchArguments = ["-carnivoreNotifySeed", origin, "-carnivoreNotifyDir", dir]
        app.launch()
        let allow = springboard.alerts.buttons["Allow"]
        if allow.waitForExistence(timeout: 12) { allow.tap() }
        Thread.sleep(forTimeInterval: 1)
        Thread.sleep(forTimeInterval: 1)

        for kind in kinds {
            FileManager.default.createFile(atPath: dir + "/want-" + kind, contents: Data())
            XCTAssertTrue(waitForFile(dir + "/pushed-" + kind), "no push for \(kind)")
            var banner = springboard.descendants(matching: .any)["NotificationShortLookView"].firstMatch
            if !banner.waitForExistence(timeout: 10) {
                let from = springboard.coordinate(withNormalizedOffset: CGVector(dx: 0.3, dy: 0.001))
                from.press(forDuration: 0.1, thenDragTo: springboard.coordinate(withNormalizedOffset: CGVector(dx: 0.3, dy: 0.7)))
                banner = springboard.descendants(matching: .any)["NotificationShortLookView"].firstMatch
                guard banner.waitForExistence(timeout: 6) else { save(kind + "-nobanner"); continue }
                Thread.sleep(forTimeInterval: 0.8)
                save(kind + "-center")
            } else {
                Thread.sleep(forTimeInterval: 0.8)
                save(kind + "-banner")
            }
            banner.press(forDuration: 1.3)
            let long = springboard.descendants(matching: .any)["NotificationLongLookView"].firstMatch
            _ = long.waitForExistence(timeout: 8)
            Thread.sleep(forTimeInterval: 6)
            save(kind + "-card")
            app.activate()
            Thread.sleep(forTimeInterval: 1)
        }
    }
}
