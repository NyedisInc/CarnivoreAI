import AVFoundation
import Speech
import UIKit

final class SpeechDictation {
    private let report: ([String: String]) -> Void
    private let engine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var recognizer: SFSpeechRecognizer?
    private var transcript = ""
    private var generation = 0
    private var backgroundWatch: NSObjectProtocol?

    init(report: @escaping ([String: String]) -> Void) {
        self.report = report
        backgroundWatch = NotificationCenter.default.addObserver(
            forName: UIApplication.didEnterBackgroundNotification, object: nil, queue: .main) { [weak self] _ in
            self?.cancel()
        }
    }

    deinit {
        if let backgroundWatch { NotificationCenter.default.removeObserver(backgroundWatch) }
        teardown()
    }

    func start() {
        cancel()
        generation += 1
        let mine = generation
        SFSpeechRecognizer.requestAuthorization { [weak self] status in
            DispatchQueue.main.async {
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
            DispatchQueue.main.async {
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
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        request.requiresOnDeviceRecognition = recognizer.supportsOnDeviceRecognition
        self.recognizer = recognizer
        self.request = request
        transcript = ""
        let mine = generation
        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            DispatchQueue.main.async {
                guard let self, mine == self.generation else { return }
                if let result {
                    self.transcript = result.bestTranscription.formattedString
                    if result.isFinal { self.finish(); return }
                    self.report(["type": "speech", "kind": "text", "text": self.transcript])
                } else if error != nil {
                    if self.transcript.isEmpty { self.fail("failed") } else { self.finish() }
                }
            }
        }
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.record, mode: .measurement, options: .duckOthers)
            try session.setActive(true, options: .notifyOthersOnDeactivation)
            let input = engine.inputNode
            input.removeTap(onBus: 0)
            input.installTap(onBus: 0, bufferSize: 1024, format: input.outputFormat(forBus: 0)) { buffer, _ in
                request.append(buffer)
            }
            engine.prepare()
            try engine.start()
        } catch {
            fail("failed")
        }
    }

    func stop() {
        guard request != nil else { return }
        stopAudio()
        request?.endAudio()
        let mine = generation
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
            guard let self, mine == self.generation, self.request != nil else { return }
            self.finish()
        }
    }

    func cancel() {
        generation += 1
        teardown()
    }

    private func finish() {
        let text = transcript
        teardown()
        generation += 1
        report(["type": "speech", "kind": "end", "text": text])
    }

    private func fail(_ reason: String) {
        teardown()
        generation += 1
        report(["type": "speech", "kind": "error", "reason": reason])
    }

    private func stopAudio() {
        if engine.isRunning { engine.stop() }
        engine.inputNode.removeTap(onBus: 0)
    }

    private func teardown() {
        stopAudio()
        task?.cancel()
        task = nil
        request = nil
        recognizer = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
    }
}
