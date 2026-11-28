import AVFoundation
import SwiftUI

enum ScanEvent: Sendable {
    case code(String)
    case cameraDenied
    case cameraUnavailable
}

struct ScannerView: UIViewControllerRepresentable {
    let onEvent: (ScanEvent) -> Void

    func makeUIViewController(context: Context) -> ScannerController {
        let controller = ScannerController()
        controller.onEvent = onEvent
        return controller
    }

    func updateUIViewController(_ controller: ScannerController, context: Context) {
        controller.onEvent = onEvent
    }
}

final class ScannerController: UIViewController, @preconcurrency AVCaptureMetadataOutputObjectsDelegate {
    var onEvent: ((ScanEvent) -> Void)?
    private let session = AVCaptureSession()
    private let sessionQueue = DispatchQueue(label: "ai.carnivore.scanner.session")
    private var preview: AVCaptureVideoPreviewLayer?
    private var configured = false

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        let layer = AVCaptureVideoPreviewLayer(session: session)
        layer.videoGravity = .resizeAspectFill
        layer.frame = view.bounds
        view.layer.addSublayer(layer)
        preview = layer

        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized: configure()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { [weak self] granted in
                DispatchQueue.main.async {
                    guard let self else { return }
                    granted ? self.configure() : self.onEvent?(.cameraDenied)
                }
            }
        default: onEvent?(.cameraDenied)
        }
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        preview?.frame = view.bounds
    }

    override func viewWillAppear(_ animated: Bool) {
        super.viewWillAppear(animated)
        let session = self.session
        sessionQueue.async {
            if !session.isRunning, !session.inputs.isEmpty { session.startRunning() }
        }
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        let session = self.session
        sessionQueue.async {
            if session.isRunning { session.stopRunning() }
        }
    }

    private func configure() {
        guard !configured else { return }
        configured = true
        let session = self.session
        sessionQueue.async { [weak self] in
            guard let self else { return }
            session.beginConfiguration()
            guard let device = AVCaptureDevice.default(for: .video),
                  let input = try? AVCaptureDeviceInput(device: device),
                  session.canAddInput(input) else {
                session.commitConfiguration()
                DispatchQueue.main.async { self.onEvent?(.cameraUnavailable) }
                return
            }
            session.addInput(input)
            let output = AVCaptureMetadataOutput()
            guard session.canAddOutput(output) else {
                session.commitConfiguration()
                DispatchQueue.main.async { self.onEvent?(.cameraUnavailable) }
                return
            }
            session.addOutput(output)
            guard output.availableMetadataObjectTypes.contains(.qr) else {
                session.commitConfiguration()
                DispatchQueue.main.async { self.onEvent?(.cameraUnavailable) }
                return
            }
            output.setMetadataObjectsDelegate(self, queue: .main)
            output.metadataObjectTypes = [.qr]
            session.commitConfiguration()
            session.startRunning()
        }
    }

    func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput objects: [AVMetadataObject],
                        from connection: AVCaptureConnection) {
        for object in objects {
            if let text = (object as? AVMetadataMachineReadableCodeObject)?.stringValue {
                onEvent?(.code(text))
                break
            }
        }
    }
}
