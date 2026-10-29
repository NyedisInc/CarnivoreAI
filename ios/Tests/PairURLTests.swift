import XCTest
@testable import Carnivore

final class PairURLTests: XCTestCase {
    private let host = "abcdefghijklmnopqrstuvwxy2.link.carnivore.ai"
    private let secret = String(repeating: "aB3_-", count: 9)

    private func parse(_ text: String, known: [Origin] = []) -> Result<PairTarget, PairError> {
        PairURL.parse(text, known: known)
    }

    func testLinkHostAcceptedAndUrlKeptExactly() throws {
        let text = "https://\(host)/pair#\(secret)"
        let target = try parse(text).get()
        XCTAssertEqual(target.url.absoluteString, text)
        XCTAssertEqual(target.origin.host, host)
        XCTAssertFalse(target.isKnown)
        XCTAssertEqual(target.kind, .relay)
    }

    func testKnownComputerAcceptedIncludingCustomDomainAndLan() throws {
        let custom = Origin(url: URL(string: "https://box.example.com")!)!
        let lan = Origin(url: URL(string: "http://198.51.100.10:8000")!)!
        let a = try parse("https://box.example.com/pair#\(secret)", known: [custom]).get()
        XCTAssertTrue(a.isKnown)
        XCTAssertEqual(a.kind, .https)
        XCTAssertTrue(try parse("http://198.51.100.10:8000/pair#\(secret)", known: [lan]).get().isKnown)
    }

    func testCustomNameAsksForConfirmation() throws {
        let text = "https://agents.example.com/pair#\(secret)"
        let target = try parse(text).get()
        XCTAssertTrue(target.needsConfirm)
        XCTAssertFalse(target.isKnown)
        XCTAssertEqual(target.kind, .https)
        XCTAssertEqual(target.url.absoluteString, text)
        XCTAssertFalse(try parse(text, known: [target.origin]).get().needsConfirm)
        XCTAssertFalse(try parse("https://\(host)/pair#\(secret)").get().needsConfirm)
    }

    func testPunycodeHostShownAsPunycode() throws {
        let target = try parse("https://xn--pple-43d.example.com/pair#\(secret)").get()
        XCTAssertTrue(target.needsConfirm)
        XCTAssertEqual(target.origin.host, "xn--pple-43d.example.com")
    }

    func testHostsRefusedOutright() {
        for text in ["http://box.example.com/pair#\(secret)", "http://\(host)/pair#\(secret)",
                     "https://\(host):8443/pair#\(secret)", "https://box.example.com:8443/pair#\(secret)",
                     "https://198.51.100.10/pair#\(secret)", "https://localhost/pair#\(secret)",
                     "https://[::1]/pair#\(secret)"] {
            XCTAssertEqual(parse(text), .failure(.unknownHost), text)
        }
    }

    func testManualAddressFollowsTheSameHostRules() throws {
        let link = Origin(url: URL(string: "https://\(host)")!)!
        let custom = Origin(url: URL(string: "https://agents.example.com")!)!
        let lan = Origin(url: URL(string: "http://198.51.100.10:8000")!)!
        XCTAssertFalse(try PairURL.manual(link, known: []).get().needsConfirm)
        let t = try PairURL.manual(custom, known: []).get()
        XCTAssertTrue(t.needsConfirm)
        XCTAssertEqual(t.url.absoluteString, "https://agents.example.com/pair")
        XCTAssertFalse(try PairURL.manual(custom, known: [custom]).get().needsConfirm)
        XCTAssertEqual(PairURL.manual(lan, known: []), .failure(.unknownHost))
    }

    func testNonPairingQrNeverClaimsAnUnknownComputer() {
        XCTAssertEqual(parse("https://box.example.com/"), .failure(.notAPairingCode))
        XCTAssertEqual(parse("https://box.example.com/pair"), .failure(.badSecret))
        XCTAssertEqual(parse("http://198.51.100.10:8000/pair#short"), .failure(.badSecret))
    }

    func testNotAPairingCodeRefused() {
        for text in ["hello", "", "carnivore://\(host)/pair#\(secret)", "https://\(host)/",
                     "https://\(host)/pair/status#\(secret)", "https://\(host)/pair?x=1#\(secret)",
                     "https://user:pw@\(host)/pair#\(secret)"] {
            XCTAssertEqual(parse(text), .failure(.notAPairingCode), text)
        }
    }

    func testMalformedSecretRefused() {
        XCTAssertEqual(parse("https://\(host)/pair"), .failure(.badSecret))
        XCTAssertEqual(parse("https://\(host)/pair#short"), .failure(.badSecret))
        XCTAssertEqual(parse("https://\(host)/pair#\(secret)%20x"), .failure(.badSecret))
    }


    private let custom = "https://agents.example.com/pair"
    private let linkId = "abcdefghijklmnopqrstuvwxy2"

    func testValidLinkParameterPairsThroughTheLinkHost() throws {
        let t = try parse("\(custom)?link=\(linkId)#\(secret)").get()
        XCTAssertEqual(t.url.absoluteString, "https://\(host)/pair#\(secret)")
        XCTAssertEqual(t.origin.host, host)
        XCTAssertEqual(t.kind, .relay)
        XCTAssertFalse(t.needsConfirm)
        let saved = try parse("\(custom)?link=\(linkId)#\(secret)", known: [t.origin]).get()
        XCTAssertTrue(saved.isKnown)
    }

    func testInvalidLinkParameterFallsBackToConfirm() throws {
        let bad = ["short", "\(linkId.uppercased())", "\(linkId)x", "\(linkId).evil.com", "\(linkId)%2Eevil",
                   "", "abcdefghijklmnopqrstuvwxy1", "\(linkId).link.carnivore.ai"]
        for value in bad {
            let t = try parse("\(custom)?link=\(value)#\(secret)").get()
            XCTAssertTrue(t.needsConfirm, value)
            XCTAssertEqual(t.kind, .https, value)
            XCTAssertEqual(t.origin.host, "agents.example.com", value)
        }
        XCTAssertEqual(parse("\(custom)?link=\(linkId)&x=1#\(secret)"), .failure(.notAPairingCode))
        XCTAssertEqual(parse("\(custom)?other=\(linkId)#\(secret)"), .failure(.notAPairingCode))
    }

    func testNoLinkParameterKeepsRoundOneBehavior() throws {
        let t = try parse("\(custom)#\(secret)").get()
        XCTAssertTrue(t.needsConfirm)
        XCTAssertEqual(t.kind, .https)
    }


    func testLinkLookalikesNeedConfirmAndNeverRelay() throws {
        for h in ["\(linkId).link.carnivore.ai.evil.com", "short.link.carnivore.ai"] {
            let t = try parse("https://\(h)/pair#\(secret)").get()
            XCTAssertTrue(t.needsConfirm, h)
            XCTAssertEqual(t.kind, .https, h)
        }
    }

    func testUnicodeLookalikeShownAsPunycode() throws {
        let t = try parse("https://\u{0430}pple.com/pair#\(secret)").get()
        XCTAssertEqual(t.origin.host, "xn--pple-43d.com")
        XCTAssertTrue(t.needsConfirm)
        XCTAssertEqual(t.kind, .https)
    }

    func testNewlineAfterLinkHostNeverRelay() {
        let r = parse("https://\(linkId).link.carnivore.ai%0A/pair#\(secret)")
        if case .success(let t) = r { XCTAssertNotEqual(t.kind, .relay) }
        let q = parse("\(custom)?link=\(linkId)%0A#\(secret)")
        if case .success(let t) = q { XCTAssertNotEqual(t.kind, .relay) }
    }

    func testSecretEndingInNewlineIsBadSecret() {
        XCTAssertEqual(parse("https://\(linkId).link.carnivore.ai/pair#\(secret)%0A"), .failure(.badSecret))
    }

    func testTrailingDotHostRefused() {
        XCTAssertEqual(parse("https://agents.example.com./pair#\(secret)"), .failure(.unknownHost))
    }
}
