import Foundation

/// CPU bakes of the shader's textures, ported line for line from the Pi
/// renderer's `make_straw`, `make_swirl`, `bake_art` and `dyn_fill`.
/// All of it runs once per dimension change, never per frame.
enum Bakes {
    @inline(__always) static func fr(_ x: Float) -> Float { x - floor(x) }

    @inline(__always) static func h2(_ x: Float, _ y: Float) -> Float {
        var px = fr(x * 0.1031), py = fr(y * 0.1031)
        let pz = px
        let d = px * (py + 33.33) + py * (pz + 33.33) + pz * (px + 33.33)
        px += d; py += d
        return fr((px + py) * (pz + d))
    }

    @inline(__always) static func n2(_ x: Float, _ y: Float) -> Float {
        let ix = floor(x), iy = floor(y)
        var fx = x - ix, fy = y - iy
        fx = fx * fx * (3 - 2 * fx)
        fy = fy * fy * (3 - 2 * fy)
        let a = h2(ix, iy), b = h2(ix + 1, iy)
        let c = h2(ix, iy + 1), d = h2(ix + 1, iy + 1)
        let ab = a + (b - a) * fx, cd = c + (d - c) * fx
        return ab + (cd - ab) * fy
    }

    @inline(__always) static func ss(_ a: Float, _ b: Float, _ x: Float) -> Float {
        var t = (x - a) / (b - a)
        t = t < 0 ? 0 : (t > 1 ? 1 : t)
        return t * t * (3 - 2 * t)
    }

    /// 1 inside the stroke of half-width w, antialiased over aa.
    @inline(__always) static func lnf(_ d: Float, _ w: Float, _ aa: Float) -> Float {
        var a = abs(d) - w
        if a >= aa { return 0 }
        if a < 0 { a = 0 }
        let t = a / aa
        return 1 - t * t * (3 - 2 * t)
    }

    @inline(__always) static func ring(_ x: Float, _ y: Float, _ cx: Float, _ cy: Float, _ r: Float) -> Float {
        let dx = x - cx, dy = y - cy
        return sqrt(dx * dx + dy * dy) - r
    }

    @inline(__always) static func segment(_ x: Float, _ y: Float,
                                          _ ax: Float, _ ay: Float, _ bx: Float, _ by: Float) -> Float {
        let pax = x - ax, pay = y - ay, bax = bx - ax, bay = by - ay
        var h = (pax * bax + pay * bay) / (bax * bax + bay * bay + 1e-9)
        h = h < 0 ? 0 : (h > 1 ? 1 : h)
        let dx = pax - bax * h, dy = pay - bay * h
        return sqrt(dx * dx + dy * dy)
    }

    @inline(__always) static func byte(_ v: Float) -> UInt8 {
        UInt8(max(0, min(255, v * 255)))
    }

    /// Fine straw backdrop, 1024x1024 RGBA8.
    static func straw(n: Int = 1024) -> [UInt8] {
        var px = [UInt8](repeating: 0, count: n * n * 4)
        let R: Float = 2.4
        for y in 0..<n {
            let qy = (Float(y) + 0.5) / Float(n) * 2 - 1
            for x in 0..<n {
                let qx = (Float(x) + 0.5) / Float(n) * 2 - 1
                let fx = qx * R, fy = qy * R
                let fn = n2(fx * 2.7, fy * 2.7)
                let row = 0.5 + 0.5 * sin(fx * 80 + fy * 28 + 2.2 * fn)
                let br = 0.90 + 0.18 * fn
                var cr = (0.12 + 0.12 * row) * br
                var cg = (0.08 + 0.09 * row) * br
                var cb = (0.03 + 0.04 * row) * br
                let m = ss(0.70, 1.05, sqrt(fx * fx + fy * fy)) * 0.5
                cr += (0.10 - cr) * m
                cg += (0.14 - cg) * m
                cb += (0.04 - cb) * m
                let o = (y * n + x) * 4
                px[o] = byte(cr); px[o + 1] = byte(cg); px[o + 2] = byte(cb); px[o + 3] = 255
            }
        }
        return px
    }

    /// Flat-disk swirl: R = sin(pattern), G = cos(pattern), so the shader
    /// rotates the time phase instead of evaluating noise per pixel.
    static func swirl(n: Int = 1024) -> [UInt8] {
        var px = [UInt8](repeating: 0, count: n * n * 4)
        for y in 0..<n {
            let qy = (Float(y) + 0.5) / Float(n) * 2 - 1
            for x in 0..<n {
                let qx = (Float(x) + 0.5) / Float(n) * 2 - 1
                let th = atan2(qy, qx)
                let r = sqrt(qx * qx + qy * qy)
                let p = th * 6 + r * 55 + 1.2 * n2(qx * 5, qy * 5)
                let o = (y * n + x) * 4
                px[o] = byte(0.5 + 0.5 * sin(p))
                px[o + 1] = byte(0.5 + 0.5 * cos(p))
                px[o + 2] = 0; px[o + 3] = 255
            }
        }
        return px
    }

    /// Baked layer sprites: 0 heptagram chords, 1 pentagram (nodes+chords),
    /// 2 vortex (R doubling circuit, G 3-6-9 axis, B nodes).
    static func art(n: Int = 1024, kind: Int) -> [UInt8] {
        var px = [UInt8](repeating: 0, count: n * n * 4)
        let R: Float = 1.2
        for y in 0..<n {
            let qy = (Float(y) + 0.5) / Float(n) * 2 - 1
            for x in 0..<n {
                let qx = (Float(x) + 0.5) / Float(n) * 2 - 1
                let fx = qx * R, fy = qy * R
                var mr: Float = 0, mg: Float = 0, mb: Float = 0
                if kind == 0 {
                    for k in 0..<7 {
                        let a0 = Float.pi * 2 * Float(k) / 7 + Float.pi / 2
                        let a1 = Float.pi * 2 * Float((k + 3) % 7) / 7 + Float.pi / 2
                        mr = max(mr, lnf(segment(fx, fy, cos(a0), sin(a0), cos(a1), sin(a1)),
                                        0.0036, 0.0032))
                    }
                } else if kind == 1 {
                    for k in 0..<5 {
                        let a0 = Float.pi * 2 * Float(k) / 5 + Float.pi / 2
                        let a1 = Float.pi * 2 * Float((k + 2) % 5) / 5 + Float.pi / 2
                        let cx = cos(a0), cy = sin(a0)
                        mr = max(mr, lnf(abs(ring(fx, fy, cx, cy, 0)) - 0.0227, 0.0064, 0.0036))
                        mr = max(mr, lnf(segment(fx, fy, cx, cy, cos(a1), sin(a1)), 0.0041, 0.0032))
                    }
                } else {
                    for k in 1...9 {
                        let a = Float.pi * 2 * Float(k) / 9 + Float.pi / 2
                        mb = max(mb, lnf(abs(ring(fx, fy, cos(a), sin(a), 0)) - 0.0289, 0.0079, 0.0036))
                    }
                    let dbl: [(Int, Int)] = [(1, 2), (2, 4), (4, 8), (8, 7), (7, 5), (5, 1)]
                    for (i0, i1) in dbl {
                        let a0 = Float.pi * 2 * Float(i0) / 9 + Float.pi / 2
                        let a1 = Float.pi * 2 * Float(i1) / 9 + Float.pi / 2
                        mr = max(mr, lnf(segment(fx, fy, cos(a0), sin(a0), cos(a1), sin(a1)),
                                        0.0063, 0.0032))
                    }
                    let ax: [(Int, Int)] = [(3, 6), (6, 9), (9, 3)]
                    for (i0, i1) in ax {
                        let a0 = Float.pi * 2 * Float(i0) / 9 + Float.pi / 2
                        let a1 = Float.pi * 2 * Float(i1) / 9 + Float.pi / 2
                        mg = max(mg, lnf(segment(fx, fy, cos(a0), sin(a0), cos(a1), sin(a1)),
                                        0.0068, 0.0032))
                    }
                }
                let o = (y * n + x) * 4
                px[o] = byte(mr); px[o + 1] = byte(mg); px[o + 2] = byte(mb); px[o + 3] = 255
            }
        }
        return px
    }

    /// Four layers for one dimension: the rose at n petals, then the cascade
    /// crowns at n, n-2, n-4 (matching the shader's m loop).
    static func dyn(_ n: Int, size: Int = 512) -> [UInt8] {
        let N = size
        var px = [UInt8](repeating: 0, count: N * N * 4 * 4)
        let R: Float = 1.2
        for layer in 0..<4 {
            let nm = layer == 0 ? Float(n) : max(Float(n) - 2 * Float(layer - 1), 3)
            let base = layer * N * N * 4
            for y in 0..<N {
                let qy = (Float(y) + 0.5) / Float(N) * 2 - 1
                for x in 0..<N {
                    let qx = (Float(x) + 0.5) / Float(N) * 2 - 1
                    let th = atan2(qy, qx)
                    let r = sqrt(qx * qx + qy * qy)
                    let fx = qx * R, fy = qy * R
                    var m: Float
                    if layer == 0 {
                        let p = 0.5 + 0.5 * cos(nm * th)
                        m = max(lnf(r - (0.92 + 0.10 * p), 0.0045, 0.0031),
                                lnf(r - (0.86 + 0.14 * p), 0.0031, 0.0022))
                        _ = fx; _ = fy
                    } else {
                        let c = abs(cos(nm * th))
                        let c2 = c * c, c4 = c2 * c2, c6 = c4 * c2
                        m = lnf(r - (0.88 + 0.12 * c6), 0.0031, 0.0022)
                    }
                    let o = base + (y * N + x) * 4
                    px[o] = byte(m); px[o + 1] = 0; px[o + 2] = 0; px[o + 3] = 255
                }
            }
        }
        return px
    }
}
