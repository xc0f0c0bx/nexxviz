import AppKit
import OpenGL.GL3
import ImageIO
import UniformTypeIdentifiers

/// Offscreen render for verification: opens a GL context without a window,
/// renders one frame at a given time and writes a PNG.
enum Snapshot {
    static func run(path: String, time: Double, width: Int, height: Int) throws {
        var attrs: [NSOpenGLPixelFormatAttribute] = [
            NSOpenGLPixelFormatAttribute(NSOpenGLPFAOpenGLProfile),
            NSOpenGLPixelFormatAttribute(NSOpenGLProfileVersion4_1Core),
            NSOpenGLPixelFormatAttribute(NSOpenGLPFAColorSize), 24,
            NSOpenGLPixelFormatAttribute(NSOpenGLPFAAlphaSize), 8,
            NSOpenGLPixelFormatAttribute(NSOpenGLPFAAccelerated),
            NSOpenGLPixelFormatAttribute(NSOpenGLPFAAllowOfflineRenderers),
            0,
        ]
        guard let format = NSOpenGLPixelFormat(attributes: &attrs),
              let context = NSOpenGLContext(format: format, share: nil) else {
            throw NSError(domain: "nexxvis", code: 5,
                          userInfo: [NSLocalizedDescriptionKey: "no OpenGL 4.1 context"])
        }
        context.makeCurrentContext()
        let body = try ShaderSource.load()
        let engine = try Engine(shaderBody: body)
        let nd = Story.autoDimension(time)
        engine.setDimensionSync(Int(nd.rounded()))

        var state = FrameState()
        state.time = time
        state.dt = 1.0 / 60
        state.frame = 1
        state.story = [nd, 0, Float(min(max(nd - 1, 0), 6)), 0.45]
        state.so = Story.so(time, nd: nd)
        state.level = [0.35, 0.40, 0.20, 0.30]
        state.elements = [0.30, 0.20, 0.15, 0.25]
        state.bandA = [0.30, 0.55, 0.35, 0.40]
        state.bandB = [0.30, 0.25, 0.30, 0.12]
        engine.render(width: width, height: height, state: state)

        let capture = engine.readPixels()
        try writePNG(path: path, width: capture.width, height: capture.height, pixels: capture.pixels)
        print("wrote \(path) (\(capture.width)x\(capture.height), t=\(time), dim=\(nd))")
    }

    static func writePNG(path: String, width: Int, height: Int, pixels: [UInt8]) throws {
        let row = width * 4
        var flipped = [UInt8](repeating: 0, count: pixels.count)
        for y in 0..<height {
            let src = (height - 1 - y) * row
            let dst = y * row
            flipped.replaceSubrange(dst..<(dst + row), with: pixels[src..<(src + row)])
        }
        guard let provider = CGDataProvider(data: Data(flipped) as CFData) else {
            throw NSError(domain: "nexxvis", code: 6, userInfo: [NSLocalizedDescriptionKey: "image provider"])
        }
        let info = CGBitmapInfo(rawValue: CGImageAlphaInfo.noneSkipLast.rawValue)
        guard let image = CGImage(width: width, height: height, bitsPerComponent: 8, bitsPerPixel: 32,
                                  bytesPerRow: row, space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: info, provider: provider, decode: nil,
                                  shouldInterpolate: false, intent: .defaultIntent) else {
            throw NSError(domain: "nexxvis", code: 7, userInfo: [NSLocalizedDescriptionKey: "image"])
        }
        guard let dest = CGImageDestinationCreateWithURL(URL(fileURLWithPath: path) as CFURL,
                                                         UTType.png.identifier as CFString, 1, nil) else {
            throw NSError(domain: "nexxvis", code: 8, userInfo: [NSLocalizedDescriptionKey: "png destination"])
        }
        CGImageDestinationAddImage(dest, image, nil)
        guard CGImageDestinationFinalize(dest) else {
            throw NSError(domain: "nexxvis", code: 9, userInfo: [NSLocalizedDescriptionKey: "png write"])
        }
    }
}
