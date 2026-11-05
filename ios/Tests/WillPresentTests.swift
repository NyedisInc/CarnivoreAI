import UserNotifications
import XCTest
@testable import Carnivore

final class WillPresentTests: XCTestCase {
    func testNoBannerOrSoundForTheSessionOnScreen() {
        let push: [AnyHashable: Any] = ["origin": "relay-a", "thread": "carnivore_api"]
        XCTAssertEqual(AppDelegate.presentation(for: push, viewing: ("relay-a", "carnivore_api")), [.list])
        XCTAssertEqual(AppDelegate.presentation(for: push, viewing: ("relay-a", "carnivore_web")), [.banner, .sound])
        XCTAssertEqual(AppDelegate.presentation(for: push, viewing: ("relay-b", "carnivore_api")), [.banner, .sound])
        XCTAssertEqual(AppDelegate.presentation(for: push, viewing: nil), [.banner, .sound])
    }
}
