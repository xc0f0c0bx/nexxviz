import Foundation

/// The shader's own chapter ladder (1..13, one step per 10 s with a glide at
/// the end of each step) plus the SO(n) group element, computed on the CPU
/// exactly as the Pi renderer does it.
enum Story {
    static func smoothstep(_ a: Double, _ b: Double, _ x: Double) -> Double {
        var t = (x - a) / (b - a)
        t = t < 0 ? 0 : (t > 1 ? 1 : t)
        return t * t * (3 - 2 * t)
    }

    static func autoDimension(_ t: Double) -> Float {
        let step = 10.0
        let autoT = t.truncatingRemainder(dividingBy: step * 13)
        let stepT = autoT.truncatingRemainder(dividingBy: step)
        let nd = 1 + floor(autoT / step) + smoothstep(6, 9, stepT)
        return Float(min(max(nd, 1), 13))
    }

    /// (cos a4, sin a4, sx, sy): the visible-plane rotation and the
    /// anisotropic shadow of the higher planes.
    static func so(_ t: Double, nd: Float) -> [Float] {
        let a = -Float(t) * 0.25
        var sx: Float = 1
        var sy: Float = 1
        for k in 0..<11 {
            let wk = nd - 2 - Float(k)
            if wk <= 0.002 { continue }
            let w = min(wk, 1)
            let ak = 0.05 + 0.03 * Float(k) + 0.02 * sin(Float(t) * 0.07 + Float(k))
            let bk = 0.06 + 0.03 * Float(k) + 0.02 * sin(Float(t) * 0.05 + Float(k) * 1.3)
            sx *= 1 + (cos(ak) - 1) * w
            sy *= 1 + (cos(bk) - 1) * w
        }
        return [cos(a), sin(a), sx, sy]
    }
}
