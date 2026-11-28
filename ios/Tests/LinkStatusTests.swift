import XCTest
@testable import Carnivore

final class LinkStatusTests: XCTestCase {
    private func parse(_ code: Int, _ json: String) -> LinkStatus {
        LinkStatus.parse(statusCode: code, body: Data(json.utf8))
    }

    func testKnownWordsMap() {
        XCTAssertEqual(parse(200, #"{"status":"up"}"#), .up)
        XCTAssertEqual(parse(200, #"{"status":"down"}"#), .down)
        XCTAssertEqual(parse(200, #"{"status":"signed_out"}"#), .signedOut)
    }

    func testAnythingElseIsUnknown() {
        XCTAssertEqual(parse(200, #"{"status":"sideways"}"#), .unknown)
        XCTAssertEqual(parse(200, "not json"), .unknown)
        XCTAssertEqual(parse(404, #"{"status":"signed_out"}"#), .unknown)
    }

    func testSignedOutReplacesOnlyLinkOffline() {
        XCTAssertEqual(UnreachableReason.linkOffline.refined(by: .signedOut), .signedOut)
        XCTAssertEqual(UnreachableReason.linkOffline.refined(by: .down), .linkOffline)
        XCTAssertEqual(UnreachableReason.linkOffline.refined(by: .unknown), .linkOffline)
        XCTAssertEqual(UnreachableReason.tlsError.refined(by: .signedOut), .tlsError)
    }

    func testSignedOutStringsNameTheComputer() {
        XCTAssertEqual(UnreachableReason.signedOut.name, "signed out")
        XCTAssertEqual(UnreachableReason.signedOut.detail(computer: "studio"),
                       "studio is signed out of carnivore. sign in on studio to reconnect your phone.")
        XCTAssertTrue(UnreachableReason.linkOffline.detail(computer: "studio")
            .hasSuffix("if it stays offline, make sure studio is signed in to carnivore."))
    }

    func testTokenShapeAndRequestKeepTokenOutOfTheURL() throws {
        XCTAssertTrue(StatusKeyStore.isWellFormed(String(repeating: "aB3_-", count: 8)))
        XCTAssertFalse(StatusKeyStore.isWellFormed("short"))
        XCTAssertFalse(StatusKeyStore.isWellFormed(String(repeating: "a", count: 21)))
        XCTAssertTrue(StatusKeyStore.isWellFormed(String(repeating: "a", count: 22)))
        XCTAssertFalse(StatusKeyStore.isWellFormed(String(repeating: "a b", count: 10)))
        let origin = try XCTUnwrap(Origin(url: URL(string: "https://abcdefghijklmnopqrstuvwxy2.link.carnivore.ai")!))
        let id = try XCTUnwrap(LinkStatusClient.deviceId(of: origin))
        let token = String(repeating: "t", count: 20)
        let request = LinkStatusClient.request(deviceId: id, token: token)
        XCTAssertEqual(request.url?.absoluteString, "https://api.carnivore.ai/v1/relay/link-status/\(id)")
        XCTAssertEqual(request.value(forHTTPHeaderField: "x-link-status-token"), token)
        XCTAssertNil(request.value(forHTTPHeaderField: "Authorization"))
        XCTAssertNil(LinkStatusClient.deviceId(of: Origin(url: URL(string: "https://example.com")!)!))
    }
}
