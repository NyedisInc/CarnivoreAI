import XCTest
@testable import Carnivore

@MainActor
final class SpeechDictationTests: XCTestCase {
    private var reports: [[String: String]] = []

    private var awake: [Bool] = []

    private func make() -> (SpeechDictation, () -> Int) {
        reports = []
        awake = []
        var started = 0
        let d = SpeechDictation(taskStarter: { _, _ in started += 1; return nil },
                                keepAwake: { self.awake.append($0) }) { self.reports.append($0) }
        d.beginTask()
        return (d, { started })
    }

    private var ends: [[String: String]] { reports.filter { $0["kind"] == "end" } }

    func testFinalResultMidCaptureStartsNewTaskAndKeepsWords() {
        let (d, started) = make()
        d.handle(Heard(text: "one two", isFinal: false, firstStart: 0, lastEnd: 1))
        d.handle(Heard(text: "one two", isFinal: true, firstStart: 0, lastEnd: 1))
        XCTAssertEqual(started(), 2)
        XCTAssertTrue(ends.isEmpty)
        XCTAssertEqual(d.transcript.text, "one two")
        d.handle(Heard(text: "three", isFinal: false, firstStart: 0, lastEnd: 0.5))
        XCTAssertEqual(d.transcript.text, "one two three")
        XCTAssertEqual(reports.last?["text"], "one two three")
    }

    func testErrorMidCaptureRestartsAndOnlyStopFinishes() {
        let (d, started) = make()
        d.handle(Heard(text: "hello", isFinal: false, firstStart: 0, lastEnd: 1))
        d.handle(nil, error: NSError(domain: "speech", code: 1))
        XCTAssertEqual(started(), 2)
        XCTAssertTrue(ends.isEmpty)
        d.stop()
        d.handle(Heard(text: "", isFinal: true))
        XCTAssertEqual(ends.count, 1)
        XCTAssertEqual(ends.first?["text"], "hello")
    }

    func testSilentResetByTimestampKeepsOldWords() {
        var t = DictationTranscript()
        t.absorb(Heard(text: "one two", firstStart: 0, lastEnd: 1))
        t.absorb(Heard(text: "one two three", firstStart: 0, lastEnd: 1.5))
        XCTAssertEqual(t.text, "one two three")
        t.absorb(Heard(text: "four", firstStart: 3, lastEnd: 3.4))
        XCTAssertEqual(t.text, "one two three four")
        t.absorb(Heard(text: "", firstStart: 0, lastEnd: 0))
        XCTAssertEqual(t.text, "one two three four")
    }

    func testSilentResetWithNoTimestampsStillKeepsOldWords() {
        var t = DictationTranscript()
        t.absorb(Heard(text: "one two"))
        t.absorb(Heard(text: "One two three"))
        XCTAssertEqual(t.text, "One two three")
        t.absorb(Heard(text: "four five"))
        XCTAssertEqual(t.text, "One two three four five")
    }

    func testKeepAwakeOnWhileListeningAndOffOnCancelStopAndBackground() {
        var (d, _) = make()
        XCTAssertEqual(awake.last, true)
        d.cancel()
        XCTAssertEqual(awake.last, false)
        (d, _) = make()
        d.handle(Heard(text: "hi"))
        d.stop()
        d.handle(Heard(text: "", isFinal: true))
        XCTAssertEqual(awake.last, false)
        (d, _) = make()
        d.interrupted()
        XCTAssertEqual(awake.last, false)
    }

    func testBackgroundDeliversHeardWordsAndEndsCapture() {
        let (d, _) = make()
        d.handle(Heard(text: "one two", firstStart: 0, lastEnd: 1))
        d.interrupted()
        XCTAssertEqual(ends.count, 1)
        XCTAssertEqual(ends.first?["text"], "one two")
        XCTAssertEqual(awake.last, false)
        d.interrupted()
        XCTAssertEqual(ends.count, 1)
    }
}
