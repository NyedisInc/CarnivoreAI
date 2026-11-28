import AVFoundation
import Speech
import UIKit

struct Heard: Equatable, Sendable {
    var text: String
    var isFinal = false
    var firstStart: TimeInterval = 0
    var lastEnd: TimeInterval = 0
}

struct DictationTranscript: Equatable, Sendable {
    private(set) var committed = ""
    private(set) var current = ""
    private var lastEnd: TimeInterval = 0

    var text: String { committed.isEmpty ? current : (current.isEmpty ? committed : committed + " " + current) }

    mutating func absorb(_ heard: Heard) {
        guard !heard.text.isEmpty else { return }
        if !current.isEmpty, !heard.text.hasPrefix(current), startsNewUtterance(heard) { commit() }
        current = heard.text
        lastEnd = heard.lastEnd
    }

    private func startsNewUtterance(_ heard: Heard) -> Bool {
        if heard.firstStart == 0, heard.lastEnd == 0 {
            let curWords = current.lowercased().split(separator: " ").map(String.init)
            let newWords = heard.text.lowercased().split(separator: " ").map(String.init)
            guard let curFirst = curWords.first, let newFirst = newWords.first else { return false }
            if curFirst == newFirst { return false }
            if curWords.count >= 2, newWords.count >= 2 {
                let curTail = Set(curWords.dropFirst())
                let shared = newWords.filter { curTail.contains($0) }.count
                if shared >= min(2, curTail.count) { return false }
            }
            return true
        }
        return heard.firstStart > lastEnd
    }

    mutating func commit() {
        guard !current.isEmpty else { return }
        committed = text
        current = ""
        lastEnd = 0
    }
}

private final class RequestBox: @unchecked Sendable {
    private let lock = NSLock()
    private var request: SFSpeechAudioBufferRecognitionRequest?

    func set(_ new: SFSpeechAudioBufferRecognitionRequest?) {
        lock.lock(); request = new; lock.unlock()
    }

    func append(_ buffer: AVAudioPCMBuffer) {
        lock.lock(); let r = request; lock.unlock()
        r?.append(buffer)
    }
}

@MainActor
final class SpeechDictation: ObservableObject {
    typealias TaskStarter = (SFSpeechAudioBufferRecognitionRequest, @escaping @Sendable (Heard?, Error?) -> Void) -> SFSpeechRecognitionTask?

    @Published private(set) var isListening = false
    @Published private(set) var liveText = ""
    @Published private(set) var errorReason: String?

    var allowCloudFallback = false

    private let report: ([String: String]) -> Void
    private let engine = AVAudioEngine()
    private let box = RequestBox()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var recognizer: SFSpeechRecognizer?
    private let injectedStarter: TaskStarter?
    private(set) var transcript = DictationTranscript()
    private(set) var tasksStarted = 0
    private var stopping = false
    private var generation = 0
    private var taskId = 0
    private var taskStartedAt = Date()
    private var heardThisTask = false
    private var quickFailures = 0
    private static let maxQuickFailures = 5
    private var watches: [NSObjectProtocol] = []
    private let keepAwake: (Bool) -> Void

    init(taskStarter: TaskStarter? = nil,
         keepAwake: @escaping (Bool) -> Void = { UIApplication.shared.isIdleTimerDisabled = $0 },
         report: @escaping ([String: String]) -> Void = { _ in }) {
        self.report = report
        self.injectedStarter = taskStarter
        self.keepAwake = keepAwake
        let center = NotificationCenter.default
        watches.append(center.addObserver(forName: UIApplication.didEnterBackgroundNotification, object: nil, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.interrupted() }
        })
        watches.append(center.addObserver(forName: AVAudioSession.interruptionNotification, object: nil, queue: .main) { [weak self] note in
            let raw = note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt
            if raw == AVAudioSession.InterruptionType.began.rawValue {
                Task { @MainActor in self?.interrupted() }
            }
        })
        watches.append(center.addObserver(forName: .AVAudioEngineConfigurationChange, object: engine, queue: .main) { [weak self] _ in
            Task { @MainActor in self?.interrupted() }
        })
    }

    deinit {
        watches.forEach { NotificationCenter.default.removeObserver($0) }
    }

    func interrupted() {
        if request != nil { finish() } else { cancel() }
    }

    func start() {
        cancel()
        generation += 1
        let mine = generation
        errorReason = nil
        liveText = ""
        report(["type": "speech", "kind": "ready"])
        SFSpeechRecognizer.requestAuthorization { [weak self] status in
            Task { @MainActor in
                guard let self, mine == self.generation else { return }
                switch status {
                case .authorized: self.requestMic(mine)
                case .restricted: self.fail("restricted")
                case .denied: self.fail("denied")
                default: self.fail("unavailable")
                }
            }
        }
    }

    private func requestMic(_ mine: Int) {
        AVAudioApplication.requestRecordPermission { [weak self] granted in
            Task { @MainActor in
                guard let self, mine == self.generation else { return }
                if granted { self.listen() } else { self.fail("denied") }
            }
        }
    }

    private func listen() {
        guard let recognizer = SFSpeechRecognizer(locale: Locale.current) ?? SFSpeechRecognizer(), recognizer.isAvailable else {
            fail("unavailable")
            return
        }
        if !recognizer.supportsOnDeviceRecognition && !allowCloudFallback {
            fail("on_device_unavailable")
            return
        }
        self.recognizer = recognizer
        transcript = DictationTranscript()
        liveText = ""
        stopping = false
        quickFailures = 0
        tasksStarted = 0
        beginTask()
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(
                .playAndRecord,
                mode: .measurement,
                options: [.defaultToSpeaker, .allowBluetooth, .duckOthers]
            )
            try session.setActive(true, options: .notifyOthersOnDeactivation)
            let input = engine.inputNode
            input.removeTap(onBus: 0)
            let format = input.outputFormat(forBus: 0)
            guard format.sampleRate > 0, format.channelCount > 0 else {
                fail("failed")
                return
            }
            let box = self.box
            input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
                box.append(buffer)
            }
            engine.prepare()
            try engine.start()
            isListening = true
        } catch {
            fail("failed")
        }
    }

    private func appleStart(_ request: SFSpeechAudioBufferRecognitionRequest,
                            _ handler: @escaping @Sendable (Heard?, Error?) -> Void) -> SFSpeechRecognitionTask? {
        guard let recognizer else { return nil }
        request.requiresOnDeviceRecognition = recognizer.supportsOnDeviceRecognition || !allowCloudFallback
        return recognizer.recognitionTask(with: request) { result, error in
            handler(result.map(Self.heard), error)
        }
    }

    private nonisolated static func heard(_ result: SFSpeechRecognitionResult) -> Heard {
        let segments = result.bestTranscription.segments
        return Heard(
            text: result.bestTranscription.formattedString,
            isFinal: result.isFinal,
            firstStart: segments.first?.timestamp ?? 0,
            lastEnd: segments.last.map { $0.timestamp + $0.duration } ?? 0
        )
    }

    func beginTask() {
        keepAwake(true)
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        self.request = request
        box.set(request)
        taskId += 1
        tasksStarted += 1
        taskStartedAt = Date()
        heardThisTask = false
        let mine = generation, thisTask = taskId
        task = (injectedStarter ?? appleStart)(request) { [weak self] heard, error in
            Task { @MainActor in
                guard let self, mine == self.generation, thisTask == self.taskId else { return }
                self.handle(heard, error: error)
            }
        }
    }

    func handle(_ heard: Heard?, error: Error? = nil) {
        if let heard {
            transcript.absorb(heard)
            if !heard.text.isEmpty { heardThisTask = true }
            liveText = transcript.text
        }
        let ended = (heard?.isFinal ?? false) || (heard == nil && error != nil)
        if ended {
            if stopping { finish(); return }
            restart()
            return
        }
        if heard != nil { report(["type": "speech", "kind": "text", "text": transcript.text]) }
    }

    private func restart() {
        transcript.commit()
        liveText = transcript.text
        if !heardThisTask && Date().timeIntervalSince(taskStartedAt) < 1 { quickFailures += 1 } else { quickFailures = 0 }
        let old = task
        task = nil
        request?.endAudio()
        request = nil
        old?.cancel()
        if quickFailures >= Self.maxQuickFailures {
            finish()
            return
        }
        beginTask()
    }

    @discardableResult
    func stop() -> String {
        guard request != nil else {
            isListening = false
            return transcript.text
        }
        stopping = true
        stopEngine()
        request?.endAudio()
        let mine = generation
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { [weak self] in
            Task { @MainActor in
                guard let self, mine == self.generation, self.stopping else { return }
                self.finish()
            }
        }
        return transcript.text
    }

    func cancel() {
        generation += 1
        stopping = false
        isListening = false
        teardown()
    }

    private func finish() {
        generation += 1
        stopping = false
        isListening = false
        transcript.commit()
        let finalText = transcript.text
        liveText = finalText
        teardown()
        report(["type": "speech", "kind": "end", "text": finalText])
    }

    private func fail(_ reason: String) {
        generation += 1
        stopping = false
        isListening = false
        errorReason = reason
        teardown()
        report(["type": "speech", "kind": "error", "reason": reason])
    }

    private func stopEngine() {
        box.set(nil)
        if engine.isRunning { engine.stop() }
        engine.inputNode.removeTap(onBus: 0)
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }

    private func teardown() {
        keepAwake(false)
        stopEngine()
        request?.endAudio()
        request = nil
        task?.cancel()
        task = nil
    }
}
