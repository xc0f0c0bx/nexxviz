import Foundation
import OpenGL.GL3

/// Per-frame values the shader needs.
struct FrameState {
    var time: Double = 0
    var dt: Double = 0
    var frame: Int32 = 0
    var level = [Float](repeating: 0, count: 4)
    var beat = [Float](repeating: 0, count: 4)
    var bpm: Float = 0
    var coverA: [Float] = [0.00, 0.67, 1.00]
    var coverB: [Float] = [1.00, 0.00, 0.67]
    var genomeA: [Float] = [119, 6.7, 0.56, 0.48]
    var genomeB: [Float] = [1.39, 0.56, 0.84, 0.31]
    var hue: Float = 0
    var entropy = [Float](repeating: 0.5, count: 4)
    var story = [Float](repeating: 0, count: 4)
    var so: [Float] = [1, 0, 1, 1]
    var elements = [Float](repeating: 0, count: 4)
    var bandA = [Float](repeating: 0, count: 4)
    var bandB = [Float](repeating: 0, count: 4)
}

/// Owns the GL program, the baked textures, the low-resolution FBO and the
/// asynchronous per-dimension rebake.
final class Engine {
    static let dynSize = 512

    private let program: GLuint
    private let blit: GLuint
    private var vao: GLuint = 0
    private var blitTex: GLint = -1
    private var fbo: GLuint = 0
    private var ftex: GLuint = 0
    private var fw = 0
    private var fh = 0
    private let scale: Float
    private var tex = [GLuint](repeating: 0, count: 10)
    private var dyntex = [GLuint](repeating: 0, count: 4)

    private let bakeLock = NSLock()
    private var bakeBusy = false
    private var bakeReady = false
    private var bakeBuf: [UInt8]?
    private var bakeN = 13
    private var dynN = 13

    private var uRes: GLint = -1, uTime: GLint = -1, uDt: GLint = -1, uFrame: GLint = -1
    private var uLevel: GLint = -1, uBeat: GLint = -1, uBPM: GLint = -1
    private var uCoverA: GLint = -1, uCoverB: GLint = -1
    private var uGenomeA: GLint = -1, uGenomeB: GLint = -1, uHue: GLint = -1
    private var uEntropy: GLint = -1, uStory: GLint = -1, uSO: GLint = -1
    private var uElements: GLint = -1, uBandA: GLint = -1, uBandB: GLint = -1
    private var uCh = [GLint](repeating: -1, count: 10)

    init(shaderBody: String) throws {
        scale = Shaders.renderScale(in: shaderBody)
        let source = Shaders.visualizer(body: shaderBody)
        guard let program = GLUtil.link(vertex: Shaders.vertex, fragment: source, label: "visualizer") else {
            throw NSError(domain: "nexxvis", code: 2,
                          userInfo: [NSLocalizedDescriptionKey: "visualizer shader failed to build"])
        }
        guard let blit = GLUtil.link(vertex: Shaders.vertex, fragment: Shaders.blitFragment, label: "blit") else {
            throw NSError(domain: "nexxvis", code: 3,
                          userInfo: [NSLocalizedDescriptionKey: "blit shader failed to build"])
        }
        self.program = program
        self.blit = blit

        glGenVertexArrays(1, &vao)
        glBindVertexArray(vao)

        // textures: 0 unused art, 1 straw, 2..4 baked layers, 5..8 dyn, 9 swirl
        tex[0] = GLUtil.makeTexture(width: 1, height: 1, pixels: [255, 255, 255, 255])
        tex[1] = GLUtil.makeTexture(width: 1024, height: 1024, pixels: Bakes.straw())
        tex[2] = GLUtil.makeTexture(width: 1024, height: 1024, pixels: Bakes.art(kind: 0))
        tex[3] = GLUtil.makeTexture(width: 1024, height: 1024, pixels: Bakes.art(kind: 1))
        tex[4] = GLUtil.makeTexture(width: 1024, height: 1024, pixels: Bakes.art(kind: 2))
        tex[9] = GLUtil.makeTexture(width: 1024, height: 1024, pixels: Bakes.swirl())
        for i in 0..<4 {
            dyntex[i] = GLUtil.makeEmptyTexture(width: Engine.dynSize, height: Engine.dynSize)
        }
        let full = Bakes.dyn(13)
        for i in 0..<4 {
            let start = i * Engine.dynSize * Engine.dynSize * 4
            let end = start + Engine.dynSize * Engine.dynSize * 4
            GLUtil.upload(dyntex[i], width: Engine.dynSize, height: Engine.dynSize,
                          pixels: Array(full[start..<end]))
        }

        glUseProgram(program)
        uRes = glGetUniformLocation(program, "iResolution")
        uTime = glGetUniformLocation(program, "iTime")
        uDt = glGetUniformLocation(program, "iTimeDelta")
        uFrame = glGetUniformLocation(program, "iFrame")
        uLevel = glGetUniformLocation(program, "iLevel")
        uBeat = glGetUniformLocation(program, "iBeat")
        uBPM = glGetUniformLocation(program, "iBPM")
        uCoverA = glGetUniformLocation(program, "iCoverA")
        uCoverB = glGetUniformLocation(program, "iCoverB")
        uGenomeA = glGetUniformLocation(program, "iGenomeA")
        uGenomeB = glGetUniformLocation(program, "iGenomeB")
        uHue = glGetUniformLocation(program, "iHue")
        uEntropy = glGetUniformLocation(program, "iEntropy")
        uStory = glGetUniformLocation(program, "iStory")
        uSO = glGetUniformLocation(program, "iSO")
        uElements = glGetUniformLocation(program, "iElements")
        uBandA = glGetUniformLocation(program, "iBandA")
        uBandB = glGetUniformLocation(program, "iBandB")
        for i in 0..<10 {
            uCh[i] = glGetUniformLocation(program, "iChannel\(i)")
            glUniform1i(uCh[i], GLint(i))
        }
        glUseProgram(blit)
        blitTex = glGetUniformLocation(blit, "tex")
        glUniform1i(blitTex, 0)
        glUseProgram(0)
    }

    /// Synchronous bake for snapshot mode (the app uses the async path).
    func setDimensionSync(_ n: Int) {
        let buffer = Bakes.dyn(n)
        let layerSize = Engine.dynSize * Engine.dynSize * 4
        for i in 0..<4 {
            GLUtil.upload(dyntex[i], width: Engine.dynSize, height: Engine.dynSize,
                          pixels: Array(buffer[(i * layerSize)..<((i + 1) * layerSize)]))
        }
        dynN = n
    }

    /// Starts a background fill when the rounded dimension changes.
    func setDimension(_ n: Int) {
        bakeLock.lock()
        if bakeBusy || n == dynN || n == bakeN {
            bakeLock.unlock()
            return
        }
        bakeBusy = true
        bakeLock.unlock()
        DispatchQueue.global(qos: .utility).async { [weak self] in
            let buffer = Bakes.dyn(n)
            guard let self else { return }
            self.bakeLock.lock()
            self.bakeBuf = buffer
            self.bakeN = n
            self.bakeReady = true
            self.bakeBusy = false
            self.bakeLock.unlock()
        }
    }

    private func uploadPendingBake() {
        bakeLock.lock()
        let ready = bakeReady
        let n = bakeN
        let buffer = bakeBuf
        bakeReady = false
        bakeBuf = nil
        bakeLock.unlock()
        guard ready, let buffer else { return }
        let layerSize = Engine.dynSize * Engine.dynSize * 4
        for i in 0..<4 {
            GLUtil.upload(dyntex[i], width: Engine.dynSize, height: Engine.dynSize,
                          pixels: Array(buffer[(i * layerSize)..<((i + 1) * layerSize)]))
        }
        dynN = n
    }

    private func resizeFBO(_ w: Int, _ h: Int) {
        if fbo == 0 {
            glGenFramebuffers(1, &fbo)
            glGenTextures(1, &ftex)
        }
        glBindTexture(GLenum(GL_TEXTURE_2D), ftex)
        glTexImage2D(GLenum(GL_TEXTURE_2D), 0, GL_RGBA8, GLsizei(w), GLsizei(h), 0,
                     GLenum(GL_RGBA), GLenum(GL_UNSIGNED_BYTE), nil)
        glTexParameteri(GLenum(GL_TEXTURE_2D), GLenum(GL_TEXTURE_MIN_FILTER), GL_LINEAR)
        glTexParameteri(GLenum(GL_TEXTURE_2D), GLenum(GL_TEXTURE_MAG_FILTER), GL_LINEAR)
        glTexParameteri(GLenum(GL_TEXTURE_2D), GLenum(GL_TEXTURE_WRAP_S), GL_CLAMP_TO_EDGE)
        glTexParameteri(GLenum(GL_TEXTURE_2D), GLenum(GL_TEXTURE_WRAP_T), GL_CLAMP_TO_EDGE)
        glBindFramebuffer(GLenum(GL_FRAMEBUFFER), fbo)
        glFramebufferTexture2D(GLenum(GL_FRAMEBUFFER), GLenum(GL_COLOR_ATTACHMENT0),
                               GLenum(GL_TEXTURE_2D), ftex, 0)
        fw = w
        fh = h
    }

    func render(width: Int, height: Int, state: FrameState) {
        let vw = max(1, Int(Float(width) * scale))
        let vh = max(1, Int(Float(height) * scale))
        if fw != vw || fh != vh { resizeFBO(vw, vh) }
        uploadPendingBake()
        glBindVertexArray(vao)

        glBindFramebuffer(GLenum(GL_FRAMEBUFFER), fbo)
        glViewport(0, 0, GLsizei(vw), GLsizei(vh))
        glDisable(GLenum(GL_BLEND))
        glClearColor(0.02, 0.02, 0.04, 1)
        glClear(GLbitfield(GL_COLOR_BUFFER_BIT))
        glUseProgram(program)
        glUniform3f(uRes, Float(vw), Float(vh), 1)
        glUniform1f(uTime, Float(state.time))
        glUniform1f(uDt, Float(state.dt))
        glUniform1i(uFrame, state.frame)
        glUniform4f(uLevel, state.level[0], state.level[1], state.level[2], state.level[3])
        glUniform4f(uBeat, state.beat[0], state.beat[1], state.beat[2], state.beat[3])
        glUniform1f(uBPM, state.bpm)
        glUniform3f(uCoverA, state.coverA[0], state.coverA[1], state.coverA[2])
        glUniform3f(uCoverB, state.coverB[0], state.coverB[1], state.coverB[2])
        glUniform4f(uGenomeA, state.genomeA[0], state.genomeA[1], state.genomeA[2], state.genomeA[3])
        glUniform4f(uGenomeB, state.genomeB[0], state.genomeB[1], state.genomeB[2], state.genomeB[3])
        glUniform1f(uHue, state.hue)
        glUniform4f(uEntropy, state.entropy[0], state.entropy[1], state.entropy[2], state.entropy[3])
        glUniform4f(uStory, state.story[0], state.story[1], state.story[2], state.story[3])
        glUniform4f(uSO, state.so[0], state.so[1], state.so[2], state.so[3])
        glUniform4f(uElements, state.elements[0], state.elements[1], state.elements[2], state.elements[3])
        glUniform4f(uBandA, state.bandA[0], state.bandA[1], state.bandA[2], state.bandA[3])
        glUniform4f(uBandB, state.bandB[0], state.bandB[1], state.bandB[2], state.bandB[3])
        for i in 0..<10 {
            glActiveTexture(GLenum(GL_TEXTURE0 + Int32(i)))
            if i >= 5 && i <= 8 {
                glBindTexture(GLenum(GL_TEXTURE_2D), dyntex[i - 5])
            } else {
                glBindTexture(GLenum(GL_TEXTURE_2D), tex[i])
            }
        }
        glDrawArrays(GLenum(GL_TRIANGLES), 0, 3)

        glBindFramebuffer(GLenum(GL_FRAMEBUFFER), 0)
        glViewport(0, 0, GLsizei(width), GLsizei(height))
        glUseProgram(blit)
        glActiveTexture(GLenum(GL_TEXTURE0))
        glBindTexture(GLenum(GL_TEXTURE_2D), ftex)
        glDrawArrays(GLenum(GL_TRIANGLES), 0, 3)
    }

    /// RGBA pixels of the low-resolution FBO, bottom row first.
    func readPixels() -> (width: Int, height: Int, pixels: [UInt8]) {
        var pixels = [UInt8](repeating: 0, count: fw * fh * 4)
        glBindFramebuffer(GLenum(GL_FRAMEBUFFER), fbo)
        glReadBuffer(GLenum(GL_COLOR_ATTACHMENT0))
        glReadPixels(0, 0, GLsizei(fw), GLsizei(fh), GLenum(GL_RGBA), GLenum(GL_UNSIGNED_BYTE), &pixels)
        return (fw, fh, pixels)
    }
}
