import AppKit
import OpenGL.GL3

/// The visualizer window: a 4.1 core OpenGL view that renders the shader
/// into a 0.42-scale FBO and blits it up, exactly like the Pi renderer.
final class VizView: NSOpenGLView {
    private var engine: Engine?
    private let audio = AudioSource()
    private var timer: Timer?
    private var startTime = ProcessInfo.processInfo.systemUptime
    private var lastFrame = ProcessInfo.processInfo.systemUptime
    private var frameIndex: Int32 = 0
    private var entropy = [Float](repeating: 0.5, count: 4)
    private var entropyCheck: Double = 0
    private var cover: [Float] = [0.00, 0.67, 1.00, 1.00, 0.00, 0.67]

    init?(viewFrame: NSRect) {
        var attrs: [NSOpenGLPixelFormatAttribute] = [
            NSOpenGLPixelFormatAttribute(NSOpenGLPFAOpenGLProfile),
            NSOpenGLPixelFormatAttribute(NSOpenGLProfileVersion4_1Core),
            NSOpenGLPixelFormatAttribute(NSOpenGLPFAColorSize), 24,
            NSOpenGLPixelFormatAttribute(NSOpenGLPFAAlphaSize), 8,
            NSOpenGLPixelFormatAttribute(NSOpenGLPFADoubleBuffer),
            NSOpenGLPixelFormatAttribute(NSOpenGLPFAAccelerated),
            NSOpenGLPixelFormatAttribute(NSOpenGLPFANoRecovery),
            0,
        ]
        guard let format = NSOpenGLPixelFormat(attributes: &attrs) else { return nil }
        super.init(frame: viewFrame, pixelFormat: format)
        wantsBestResolutionOpenGLSurface = true
    }

    required init?(coder: NSCoder) { fatalError("not used") }

    deinit { timer?.invalidate() }

    override func prepareOpenGL() {
        super.prepareOpenGL()
        openGLContext?.makeCurrentContext()
        var swap: GLint = 1
        openGLContext?.setValues(&swap, for: .swapInterval)
        do {
            engine = try Engine(shaderBody: ShaderSource.load())
        } catch {
            FileHandle.standardError.write(Data("nexxvis: \(error)\n".utf8))
            return
        }
        audio.start()
        let timer = Timer(timeInterval: 1.0 / 60.0, repeats: true) { [weak self] _ in
            self?.needsDisplay = true
        }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
    }

    override func reshape() {
        super.reshape()
        needsDisplay = true
    }

    override func draw(_ dirtyRect: NSRect) {
        guard let context = openGLContext, let engine else { return }
        context.makeCurrentContext()
        let now = ProcessInfo.processInfo.systemUptime
        let time = now - startTime
        var dt = now - lastFrame
        if dt <= 0 || dt > 0.5 { dt = 1.0 / 60 }
        lastFrame = now

        let analyzer = audio.analyzer
        analyzer.update(samples: audio.latest(), lastAudio: audio.lastSampleTime, dt: dt, now: now)

        let nd = Story.autoDimension(time)
        engine.setDimension(Int(nd.rounded()))
        if time >= entropyCheck {
            for i in 0..<4 { entropy[i] = Float.random(in: 0...1) }
            entropyCheck = time + 25
        }

        let energy = (analyzer.level[0] + analyzer.level[1] + analyzer.level[2] + analyzer.level[3]) / 4
        var state = FrameState()
        state.time = time
        state.dt = dt
        state.frame = frameIndex
        state.level = analyzer.level
        state.beat = [analyzer.beatPulse, analyzer.beatPhase, 1, analyzer.beatConfidence]
        state.bpm = analyzer.bpm
        state.coverA = [cover[0], cover[1], cover[2]]
        state.coverB = [cover[3], cover[4], cover[5]]
        state.genomeA = [119, 6.7, 0.56, 0.48]
        state.genomeB = [1.39, 0.56, 0.84, 0.31]
        state.hue = Float(sin(time * 0.05)) * 0.12
        state.entropy = entropy
        state.story = [nd, 0, Float(min(max(nd - 1, 0), 6)), energy]
        state.so = Story.so(time, nd: nd)
        state.elements = analyzer.elem
        state.bandA = Array(analyzer.band8Level[0..<4])
        state.bandB = Array(analyzer.band8Level[4..<8])

        let backing = convertToBacking(bounds).size
        engine.render(width: Int(backing.width), height: Int(backing.height), state: state)
        frameIndex += 1
        context.flushBuffer()

        if let window = window {
            let title = "Nexxvis — \(audio.mode)"
            if window.title != title { window.title = title }
        }
    }
}
