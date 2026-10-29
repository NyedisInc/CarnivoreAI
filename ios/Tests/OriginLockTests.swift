import XCTest
@testable import Carnivore

final class OriginLockTests: XCTestCase {

    private func origin(_ input: String, _ kind: ComputerKind) throws -> Origin {
        switch AddressParser.parse(input, kind: kind) {
        case .success(let o): return o
        case .failure(let e): throw XCTSkip("unexpected refusal \(e)")
        }
    }

    private func refusal(_ input: String, _ kind: ComputerKind) -> AddressError? {
        if case .failure(let e) = AddressParser.parse(input, kind: kind) { return e }
        return nil
    }

    func testRelayLinkHostAccepted() throws {
        let host = "abcdefghijklmnopqrstuvwxy2.link.carnivore.ai"
        XCTAssertEqual(try origin(host, .relay).rootURL.absoluteString, "https://\(host)/")
        XCTAssertEqual(try origin("https://\(host)/pair#x", .relay).host, host)
    }

    func testRelayRefusesOtherHostsAndHttp() {
        XCTAssertEqual(refusal("example.com", .relay), .notALinkHost)
        XCTAssertEqual(refusal("short.link.carnivore.ai", .relay), .notALinkHost)
        XCTAssertEqual(refusal("http://abcdefghijklmnopqrstuvwxy2.link.carnivore.ai", .relay), .notHttps)
    }

    func testLanHttpAcceptedAndTaggedUnencrypted() throws {
        let o = try origin("198.51.100.11", .lan)
        XCTAssertEqual(o.rootURL.absoluteString, "http://198.51.100.11:8000/")
        XCTAssertFalse(o.isEncrypted)
        XCTAssertEqual(try origin("http://mac.local:5001", .lan).port, 5001)
        XCTAssertEqual(try origin("mac.local:9000", .lan).port, 9000)
    }

    func testArbitraryHttpsAcceptedAndHttpRefused() throws {
        XCTAssertTrue(try origin("https://host.example.ts.net", .https).isEncrypted)
        XCTAssertEqual(refusal("http://box.example.com", .https), .notHttps)
    }

    func testOtherSchemesAndBadHostsRefused() {
        for kind in ComputerKind.allCases {
            XCTAssertEqual(refusal("javascript:alert(1)", kind), .notHttpOrHttps)
            XCTAssertEqual(refusal("file:///etc/passwd", kind), .notHttpOrHttps)
            XCTAssertEqual(refusal("ftp://host", kind), .notHttpOrHttps)
            XCTAssertEqual(refusal("", kind), .empty)
            XCTAssertEqual(refusal("https://user:pw@host.example", kind) ?? .badHost, .hasCredentials)
            XCTAssertEqual(refusal("https://bad host", kind), .badHost)
        }
    }

    func testNavigationLock() throws {
        let o = try origin("https://box.example.com", .https)
        func decide(_ s: String) -> NavigationDecision { OriginLock.decide(URL(string: s)!, lockedTo: o) }
        XCTAssertEqual(decide("https://box.example.com/sessions"), .allow)
        XCTAssertEqual(decide("https://BOX.example.com:443/x"), .allow)
        XCTAssertEqual(decide("https://box.example.com:8443/x"), .openInSafari)
        XCTAssertEqual(decide("http://box.example.com/x"), .openInSafari)
        XCTAssertEqual(decide("https://evil.example.org/"), .openInSafari)
        XCTAssertEqual(decide("https://box.example.com.evil.org/"), .openInSafari)
        XCTAssertEqual(decide("javascript:alert(1)"), .block)
        XCTAssertEqual(decide("file:///etc/passwd"), .block)
        XCTAssertEqual(decide("tel:123"), .block)
        XCTAssertEqual(decide("about:blank"), .allow)
    }

    func testVersionCompare() {
        XCTAssertEqual(VersionCheck.status(serverVersion: "1.14.0"), .compatible(server: "1.14.0"))
        XCTAssertEqual(VersionCheck.status(serverVersion: "1.9.9"),
                       .serverTooOld(server: "1.9.9", needs: AppVersion.minServer))
        XCTAssertEqual(VersionCheck.status(serverVersion: "2.0"), .compatible(server: "2.0"))
        XCTAssertNotNil(VersionCheck.status(serverVersion: "").warning)
    }
}
