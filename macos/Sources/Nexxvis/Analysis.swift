import Foundation
import Accelerate

/// The Pi's audio analysis, ported to vDSP: 2048-point FFT, 512 log-spaced
/// spectrum bins, three broad levels, eight perceptual bands with slow AGC
/// and fast flux, four musical elements, and a simple spectral-flux beat.
final class Analyzer {
    static let fftN = 2048
    static let bins = 512
    static let magBins = 1024

    private let log2n = vDSP_Length(11)
    private let setup: FFTSetup
    private var window = [Float](repeating: 0, count: Analyzer.fftN)
    private var re = [Float](repeating: 0, count: Analyzer.fftN)
    private var im = [Float](repeating: 0, count: Analyzer.fftN)
    private var mag = [Float](repeating: 0, count: Analyzer.magBins)
    private var prevMag = [Float](repeating: 0, count: Analyzer.magBins)
    private var binLo = [Int](repeating: 0, count: Analyzer.bins)
    private var binHi = [Int](repeating: 0, count: Analyzer.bins)
    private var binBand = [UInt8](repeating: 0, count: Analyzer.bins)
    private var binB8 = [UInt8](repeating: 0, count: Analyzer.bins)
    private var spec = [Float](repeating: 0, count: Analyzer.bins)

    var level = [Float](repeating: 0, count: 4)
    private var agc = [Float](repeating: 0.05, count: 4)
    private var band8Agc = [Float](repeating: 0.05, count: 8)
    private var band8Prev = [Float](repeating: 0, count: 8)
    var band8Level = [Float](repeating: 0, count: 8)
    private var band8Flux = [Float](repeating: 0, count: 8)
    var elem = [Float](repeating: 0, count: 4)

    var beatPulse: Float = 0
    var beatPhase: Float = 0
    var bpm: Float = 0
    var beatConfidence: Float = 0

    private var fluxAvg: Float = 0
    private var lastBeat: Double = -10
    private var intervals: [Double] = []

    init() {
        setup = vDSP_create_fftsetup(log2n, FFTRadix(kFFTRadix2))!
        for i in 0..<Analyzer.fftN {
            window[i] = 0.5 - 0.5 * cos(2 * Float.pi * Float(i) / Float(Analyzer.fftN - 1))
        }
        let fmin: Float = 30, fmax: Float = 16000
        let hzPerBin = 48000 / Float(Analyzer.fftN)
        for b in 0..<Analyzer.bins {
            let f0 = fmin * powf(fmax / fmin, Float(b) / Float(Analyzer.bins))
            let f1 = fmin * powf(fmax / fmin, Float(b + 1) / Float(Analyzer.bins))
            var lo = Int(floor(f0 / hzPerBin))
            var hi = Int(ceil(f1 / hzPerBin))
            if lo < 1 { lo = 1 }
            if hi <= lo { hi = lo + 1 }
            if hi > Analyzer.fftN / 2 { hi = Analyzer.fftN / 2 }
            binLo[b] = lo
            binHi[b] = hi
            let f = fmin * powf(fmax / fmin, (Float(b) + 0.5) / Float(Analyzer.bins))
            binBand[b] = f < 150 ? 0 : (f < 2000 ? 1 : 2)
            binB8[b] = f < 60 ? 0 : f < 120 ? 1 : f < 250 ? 2 : f < 500 ? 3
                     : f < 1000 ? 4 : f < 2500 ? 5 : f < 6000 ? 6 : 7
        }
    }

    deinit { vDSP_destroy_fftsetup(setup) }

    /// `samples` is the newest 2048 mono samples in chronological order.
    func update(samples: [Float], lastAudio: Double, dt: Double, now: Double) {
        let stale = now - lastAudio > 0.5
        for i in 0..<Analyzer.fftN {
            re[i] = stale ? 0 : samples[i] * window[i]
            im[i] = 0
        }
        re.withUnsafeMutableBufferPointer { rp in
            im.withUnsafeMutableBufferPointer { ip in
                var split = DSPSplitComplex(realp: rp.baseAddress!, imagp: ip.baseAddress!)
                vDSP_fft_zrip(setup, &split, 1, log2n, FFTDirection(FFT_FORWARD))
            }
        }
        for k in 0..<Analyzer.magBins {
            mag[k] = sqrt(re[k] * re[k] + im[k] * im[k]) * 0.5
        }

        let attack = Float(1 - exp(-dt / 0.03))
        let release = Float(1 - exp(-dt / 0.25))
        var band = [Float](repeating: 0, count: 3)
        var bandn = [Float](repeating: 0, count: 3)
        var b8 = [Float](repeating: 0, count: 8)
        var b8n = [Float](repeating: 0, count: 8)
        for b in 0..<Analyzer.bins {
            var m: Float = 0
            for k in binLo[b]..<binHi[b] {
                let v = re[k] * re[k] + im[k] * im[k]
                if v > m { m = v }
            }
            let db = 10 * log10(m + 1e-12) - 20 * log10(Float(Analyzer.fftN) / 4)
            var v = (db + 72) / 66
            v = v < 0 ? 0 : (v > 1 ? 1 : v)
            let k = v > spec[b] ? attack : release
            spec[b] += (v - spec[b]) * k
            band[Int(binBand[b])] += spec[b]
            bandn[Int(binBand[b])] += 1
            b8[Int(binB8[b])] += spec[b]
            b8n[Int(binB8[b])] += 1
        }
        var raw = [Float](repeating: 0, count: 4)
        for i in 0..<3 { raw[i] = bandn[i] > 0 ? band[i] / bandn[i] : 0 }
        raw[3] = (raw[0] + raw[1] + raw[2]) / 3
        for i in 0..<4 {
            let target = raw[i] > agc[i] ? raw[i] : agc[i] * (1 - Float(dt) / 20)
            agc[i] = max(target, 0.05)
            var v = raw[i] / agc[i]
            v = v * v
            let k = v > level[i] ? attack : release
            level[i] += (min(v, 1) - level[i]) * k
        }
        for j in 0..<8 {
            let rawb = b8n[j] > 0 ? b8[j] / b8n[j] : 0
            let target = rawb > band8Agc[j] ? rawb : band8Agc[j] * (1 - Float(dt) / 20)
            band8Agc[j] = max(target, 0.05)
            var v = rawb / band8Agc[j]
            v = v * v
            if v > 1 { v = 1 }
            let k = v > band8Level[j] ? attack : release
            band8Level[j] += (v - band8Level[j]) * k
            let fl = band8Level[j] - band8Prev[j]
            band8Flux[j] = max(fl, 0)
            band8Prev[j] = band8Level[j]
        }

        let eatk = Float(1 - exp(-dt / 0.012))
        let erel = Float(1 - exp(-dt / 0.20))
        let et: [Float] = [
            band8Level[1] * 0.85 + band8Flux[1] * 7,
            band8Level[5] * 0.55 + band8Flux[5] * 5 + band8Flux[6] * 2.5,
            band8Level[7] * 0.70 + band8Flux[7] * 6,
            band8Level[3] * 0.60 + band8Level[4] * 0.40,
        ]
        for i in 0..<4 {
            let v = min(max(et[i], 0), 1)
            let k = v > elem[i] ? eatk : erel
            elem[i] += (v - elem[i]) * k
        }

        updateBeat(now: now)
        for k in 0..<Analyzer.magBins { prevMag[k] = mag[k] }
    }

    private func updateBeat(now: Double) {
        var flux: Float = 0
        for k in 1..<512 { flux += max(mag[k] - prevMag[k], 0) }
        flux /= 512
        fluxAvg += (flux - fluxAvg) * 0.05
        let threshold = fluxAvg * 1.6 + 0.0015
        if flux > threshold && now - lastBeat > 0.22 {
            if lastBeat > 0 {
                let gap = now - lastBeat
                if gap > 0.25 && gap < 1.2 {
                    intervals.append(gap)
                    if intervals.count > 8 { intervals.removeFirst() }
                    let avg = intervals.reduce(0, +) / Double(intervals.count)
                    bpm = Float(60 / avg)
                    beatConfidence = intervals.count >= 3 ? 0.85 : 0.4
                }
            }
            lastBeat = now
        }
        let elapsed = max(now - lastBeat, 0)
        beatPulse = Float(exp(-elapsed / 0.12))
        let period = bpm > 0 ? 60 / Double(bpm) : 0.5
        beatPhase = Float((elapsed / period).truncatingRemainder(dividingBy: 1))
    }
}
