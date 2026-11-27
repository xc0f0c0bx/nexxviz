import Foundation

/// The GLSL strings that wrap the shared shader body.
///
/// The Pi renderer prepends a GLES 3.0 header to `15-crop-genesis.frag`.
/// On macOS we render with a 4.1 core context, where the body is source
/// compatible: `texture()`, `mat2`, `atan(y,x)` and the integer casts all
/// behave the same.  Only the version line, the precision statement and the
/// fragment output differ.
enum Shaders {
    static let header = [
        "#version 410 core",
        "uniform vec3 iResolution; uniform float iTime; uniform float iTimeDelta; uniform int iFrame;",
        "uniform sampler2D iChannel0; uniform sampler2D iChannel1; uniform sampler2D iChannel2; uniform sampler2D iChannel3; uniform sampler2D iChannel4; uniform sampler2D iChannel5; uniform sampler2D iChannel6; uniform sampler2D iChannel7; uniform sampler2D iChannel8; uniform sampler2D iChannel9; uniform vec4 iLevel;",
        "uniform vec4 iBeat;",
        "uniform float iBPM;",
        "uniform vec3 iCoverA; uniform vec3 iCoverB;",
        "uniform vec4 iGenomeA; uniform vec4 iGenomeB;",
        "uniform vec4 iEntropy;",
        "uniform vec4 iStory;",
        "uniform vec4 iSO;",
        "uniform vec4 iElements;",
        "uniform vec4 iBandA;",
        "uniform vec4 iBandB;",
        "uniform float iHue;",
        "out vec4 nv_FragColor;",
        "#line 1",
    ].joined(separator: "\n") + "\n"

    static let tail = "\nvoid main(){ vec4 c = vec4(0.0); mainImage(c, gl_FragCoord.xy); nv_FragColor = vec4(c.rgb, 1.0); }\n"

    /// Fullscreen triangle; `vuv` is 0..1 across the screen for the blit.
    static let vertex = [
        "#version 410 core",
        "out vec2 vuv;",
        "void main(){ vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2)); vuv = p; gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0); }",
    ].joined(separator: "\n") + "\n"

    /// Upscale of the low-resolution visualizer FBO into the window.
    static let blitFragment = [
        "#version 410 core",
        "in vec2 vuv; out vec4 o; uniform sampler2D tex;",
        "void main(){ o = vec4(texture(tex, vuv).rgb, 1.0); }",
    ].joined(separator: "\n") + "\n"

    static func visualizer(body: String) -> String {
        header + body + tail
    }

    /// `nv:scale=0.42` in the shader header sets the internal render scale,
    /// exactly as on the Pi.
    static func renderScale(in body: String) -> Float {
        for line in body.split(separator: "\n") {
            guard let range = line.range(of: "nv:scale=") else { continue }
            let tail = line[range.upperBound...]
            let number = tail.prefix { $0.isNumber || $0 == "." }
            if let v = Float(number), v > 0.05, v <= 1.0 { return v }
        }
        return 0.42
    }
}
