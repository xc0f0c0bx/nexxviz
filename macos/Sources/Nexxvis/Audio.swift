import Foundation
import AVFoundation
import ScreenCaptureKit
import CoreMedia

/// Captures the Mac's system audio through ScreenCaptureKit and keeps the
/// newest 2048 mono samples for the FFT.  If screen capture is not
/// permitted or fails, it falls back to the microphone so the visualizer
/// still moves.
final class AudioSource: NSObject {
    private let lock = NSLock()
    private var ring = [Float](repeating: 0, count: Analyzer.fftN)
    private var writeIndex = 0
    private var lastAudio: Double = 0
    private let audioQueue = DispatchQueue(label: "fm.nexxxen.capture")
    let analyzer = Analyzer()
    private(set) var mode = "starting"
    private var stream: SCStream?
    private var engine: AVAudioEngine?

    func latest() -> [Float] {
        lock.lock()
        defer { lock.unlock() }
        var out = [Float](repeating: 0, count: Analyzer.fftN)
        for i in 0..<Analyzer.fftN {
            out[i] = ring[(writeIndex + i) % Analyzer.fftN]
        }
        return out
    }

    var lastSampleTime: Double {
        lock.lock()
        defer { lock.unlock() }
        return lastAudio
    }

    private func push(_ mono: UnsafeBufferPointer<Float>) {
        lock.lock()
        for v in mono {
            ring[writeIndex] = v
            writeIndex = (writeIndex + 1) % Analyzer.fftN
        }
        lastAudio = ProcessInfo.processInfo.systemUptime
        lock.unlock()
    }

    /// Starts system-audio capture; falls back to the mic when that fails.
    func start() {
        Task {
            do {
                try await startSystemAudio()
                mode = "system audio"
            } catch {
                FileHandle.standardError.write(Data("nexxvis: system audio unavailable (\(error)); using microphone\n".utf8))
                startMicrophone()
                mode = "microphone"
            }
        }
    }

    private func startSystemAudio() async throws {
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        guard let display = content.displays.first else {
            throw NSError(domain: "nexxvis", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "no display for audio capture"])
        }
        let filter = SCContentFilter(display: display, excludingWindows: [])
        let config = SCStreamConfiguration()
        config.width = 2
        config.height = 2
        config.minimumFrameInterval = CMTime(value: 1, timescale: 2)
        config.capturesAudio = true
        config.excludesCurrentProcessAudio = true
        config.sampleRate = 48000
        config.channelCount = 2
        let stream = SCStream(filter: filter, configuration: config, delegate: self)
        try stream.addStreamOutput(self, type: .audio, sampleHandlerQueue: audioQueue)
        try await stream.startCapture()
        self.stream = stream
    }

    private func startMicrophone() {
        let engine = AVAudioEngine()
        let input = engine.inputNode
        let format = input.inputFormat(forBus: 0)
        input.installTap(onBus: 0, bufferSize: 2048, format: format) { [weak self] buffer, _ in
            guard let self, let data = buffer.floatChannelData else { return }
            let frames = Int(buffer.frameLength)
            let channels = Int(buffer.format.channelCount)
            guard frames > 0, channels > 0 else { return }
            var mono = [Float](repeating: 0, count: frames)
            for c in 0..<channels {
                for i in 0..<frames { mono[i] += data[c][i] }
            }
            for i in 0..<frames { mono[i] /= Float(channels) }
            mono.withUnsafeBufferPointer { self.push($0) }
        }
        engine.prepare()
        do {
            try engine.start()
            self.engine = engine
        } catch {
            FileHandle.standardError.write(Data("nexxvis: microphone failed: \(error)\n".utf8))
        }
    }
}

extension AudioSource: SCStreamOutput, SCStreamDelegate {
    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .audio, sampleBuffer.isValid else { return }
        var list = AudioBufferList()
        var block: CMBlockBuffer?
        let status = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sampleBuffer,
            bufferListSizeNeededOut: nil,
            bufferListOut: &list,
            bufferListSize: MemoryLayout<AudioBufferList>.size,
            blockBufferAllocator: nil,
            blockBufferMemoryAllocator: nil,
            flags: 0,
            blockBufferOut: &block)
        guard status == noErr else { return }
        let buffers = UnsafeMutableAudioBufferListPointer(&list)
        var mono = [Float]()

        if buffers.count >= 2,
           let first = buffers[0].mData,
           let second = buffers[1].mData,
           buffers[0].mNumberChannels == 1 || buffers[1].mNumberChannels == 1 {
            let n = min(Int(buffers[0].mDataByteSize), Int(buffers[1].mDataByteSize)) / 4
            let a = first.assumingMemoryBound(to: Float.self)
            let b = second.assumingMemoryBound(to: Float.self)
            mono = (0..<max(n, 0)).map { (a[$0] + b[$0]) * 0.5 }
        } else if let first = buffers.first, let data = first.mData {
            let channels = Int(first.mNumberChannels)
            let n = Int(first.mDataByteSize) / 4
            let p = data.assumingMemoryBound(to: Float.self)
            if channels <= 1 {
                mono = Array(UnsafeBufferPointer(start: p, count: n))
            } else {
                let frames = n / channels
                mono = (0..<frames).map { i in
                    var sum: Float = 0
                    for c in 0..<channels { sum += p[i * channels + c] }
                    return sum / Float(channels)
                }
            }
        }
        guard !mono.isEmpty else { return }
        mono.withUnsafeBufferPointer { push($0) }
    }
}
