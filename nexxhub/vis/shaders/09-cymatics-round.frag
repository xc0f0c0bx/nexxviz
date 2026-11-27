// Cymatics Round — a circular plate's centrally symmetric nodal figures.
// Wikipedia/Cymatics: a homogeneous body's normal modes are fixed by its
// shape, the driving spectrum selects which mode is displayed, and powder
// collects on the nodal lines. A round plate gives J_n(k r) * cos(nθ)
// modes: concentric nodal circles from the Bessel zeros and n radial nodal
// lines. n comes from the treble band, k from the bass, the beat rings a
// transient higher mode, and sand grain/sparkles sit on the nodes.
// nv:scale=0.45
//
vec3 hueShift(vec3 c, float a) {
    const vec3 k = vec3(0.57735027);
    float ca = cos(a);
    return c * ca + cross(k, c) * sin(a) + k * dot(k, c) * (1.0 - ca);
}
vec3 gA, gB;

float nvHash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453);
}

float nvNoise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = nvHash(i);
    float b = nvHash(i + vec2(1.0, 0.0));
    float c = nvHash(i + vec2(0.0, 1.0));
    float d = nvHash(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

/* J0 and J1 (Abramowitz & Stegun 9.4), asymptotic beyond x = 8. */
void nvJ01(float x, out float j0, out float j1) {
    const float PI = 3.14159265;
    x = max(x, 0.001);
    if (x < 8.0) {
        float t = x / 3.0, t2 = t * t;
        j0 = 1.0 + t2 * (-2.2499997 + t2 * (1.2656208
             + t2 * (-0.3163866 + t2 * (0.0444479
             + t2 * (-0.0039444 + t2 * 0.0002100)))));
        j1 = 0.5 * x * (1.0 + t2 * (-0.56249985 + t2 * (0.21093573
             + t2 * (-0.03954289 + t2 * (0.00443319
             + t2 * (-0.00031761 + t2 * 0.00001109))))));
    } else {
        float a = sqrt(2.0 / (PI * x));
        j0 = a * cos(x - 0.7853982);
        j1 = a * cos(x - 2.3561945);
    }
}

/* J_n for integer n = 0..3 via the recurrence, amplitude-compensated. */
float nvBessel(float n, float x) {
    float j0, j1;
    nvJ01(x, j0, j1);
    float j = j0;
    if (n > 0.5) j = j1;
    if (n > 1.5) {
        float j2 = (2.0 / max(x, 0.05)) * j1 - j0;
        j = j2;
        if (n > 2.5) j = (4.0 / max(x, 0.05)) * j2 - j1;
    }
    return j * sqrt(x + 0.15);   /* even out the 1/sqrt(x) decay */
}

float nvRoundMode(vec2 q, float n, float k, float ph, float r, float th) {
    return nvBessel(n, k * r) * cos(n * th + ph);
}

float nvBurst(float rs, float ths, float env, float maxR, float tailK,
              float ringK, float rays, float ph) {
    env = clamp(env, 0.0, 1.0);
    float amp = pow(env, 0.65);          /* fade a little faster */
    float front = (1.0 - env) * maxR;
    float d = rs - front;
    float ring = exp(-abs(d) * ringK);
    float inward = d < 0.0 ? exp(d * tailK) : 0.0;
    float ray = pow(0.5 + 0.5 * sin(ths * rays + ph), 1.6);
    return amp * (ring + inward * 0.70 * ray);
}

void mainImage(out vec4 c, in vec2 p) {
    vec2 uv = (p - 0.5 * iResolution.xy) / iResolution.y;
    float t = iTime, bass = iLevel.x, mid = iLevel.y, treb = iLevel.z;
    float beat = iBeat.x * iBeat.w;
    float phase = iBeat.y;
    float e0 = iEntropy.x, e1 = iEntropy.y, e2 = iEntropy.z, e3 = iEntropy.w;
    /* detected elements and perceptual bands */
    float kick = iElements.x, snare = iElements.y, hat = iElements.z, vocal = iElements.w;
    float lowMix = 0.5 * bass + 0.5 * max(iBandA.x, iBandA.y);
    float highMix = 0.5 * treb + 0.5 * max(iBandB.z, iBandB.w);
    gA = hueShift(iCoverA, iHue);
    gB = hueShift(iCoverB, iHue);

    /* genetic variation (evolve.py) */
    float gDens  = clamp(iGenomeA.x / 120.0, 0.35, 2.0);
    float gBands = clamp(iGenomeA.y, 3.0, 8.0);
    float gTaper = clamp(iGenomeA.z, 0.20, 0.90);
    float gGlow  = clamp(iGenomeA.w, 0.10, 0.90);
    float gInt   = clamp(iGenomeB.x, 0.70, 1.70);
    float gCol   = clamp(iGenomeB.y, 0.00, 1.00);
    float gZoom  = clamp(iGenomeB.z, 0.65, 1.35);
    float gBend  = clamp(iGenomeB.w, 0.00, 0.45);

    vec2 qs = uv / (0.68 * gZoom);          /* fixed dish coordinates */
    vec2 q = qs;
    q -= 0.040 * vec2(cos(t * 0.12), sin(t * 0.11));   /* centre orbit */
    float rot = t * 0.024 + 0.08 * sin(t * 0.031);      /* slow precession */
    q = mat2(cos(rot), -sin(rot), sin(rot), cos(rot)) * q;
    float r = length(q);
    float rs = length(qs);
    float th = atan(q.y, q.x) + gBend * 0.20 * sin(t * 0.05);

    /* spectrum selects the mode: n angular, k radial (Bessel zeros) */
    float nf = 1.2 + 2.0 * highMix + (gBands - 5.0) * 0.25
             + 0.6 * sin(t * 0.07);
    nf = max(nf, 0.5);
    float n0 = floor(nf);
    float wv = smoothstep(0.42, 0.58, fract(nf));
    float n1 = n0 + 1.0;
    float k = 5.8 + 4.0 * lowMix + 1.0 * kick + (gDens - 1.0) * 1.5
            + 0.8 * sin(t * 0.05) + gBend * 1.5 + 0.6 * (e1 - 0.5);
    float ph = 0.25 * beat + 0.15 * sin(t * 0.03)
             + gBend * 0.30 * sin(t * 0.08) + 0.18 * (e2 - 0.5);

    float f0 = nvRoundMode(q, n0, k, ph, r, th);
    float f1 = nvRoundMode(q, n1, k + 0.6, -ph, r, th);
    float ft = nvRoundMode(q, n1 + 1.0, k + 1.4, ph + 0.7 * beat, r, th);
    float env = exp(-phase * 3.0);
    float w1 = 0.35 * (0.5 + 0.5 * env);

    /* sand on the nodes; fade the geometric centre point */
    float cfade = smoothstep(0.02, 0.14, r);
    float line = mix(exp(-abs(f0) * 12.0), exp(-abs(f1) * 13.0), wv)
               + 0.18 * max(beat, kick) * exp(-abs(ft) * 11.0);
    line *= cfade;
    /* travelling sound waves along the nodal strings */
    float wave = sin(r * (9.0 + 8.0 * iBandA.z) - t * (2.0 + 2.5 * beat)
                     + th * 3.0)
               * sin(r * (5.0 + 4.0 * iBandB.y) + t * (1.2 + 1.5 * beat)
                     - th * 2.0);
    float waveAmt = 0.25 + 0.55 * mid + 0.35 * kick;
    line *= 0.72 + 0.45 * (0.5 + 0.5 * wave) * waveAmt;

    float grain = nvHash(floor((uv + vec2(e3 * 3.0, e0 * 3.0)) * 430.0));
    float spark = smoothstep(0.975, 1.0, grain);
    spark = max(spark, smoothstep(0.985, 1.0, grain) * hat);
    /* vivid palette sweep over radius and a periodic angular lobe */
    float hue = 0.20 * r + 0.09 * sin(3.0 * th + 0.8) + 0.05 * t
              + 0.45 * gCol + 0.03 * vocal;
    vec3 hot = mix(gA, gB, 0.5 + 0.5 * sin(6.2831853 * hue));
    hot = mix(hot, vec3(1.0), 0.12 * snare);
    hot = hot * 1.55 + 0.10;                  /* saturation and lift */
    vec3 sand = mix(vec3(0.96, 0.88, 0.70), hot, 0.55 + 0.35 * gCol);
    sand *= 0.80 + 0.30 * grain;

    /* soft background bloom: wide, low-frequency copy of the field */
    float soft = exp(-abs(f0) * 1.4) * 0.60 + exp(-abs(f1) * 1.8) * 0.35;
    vec3 backCol = hot * soft * (0.14 + 0.10 * beat)
                 + mix(gA, gB, 0.5) * soft * 0.04;

    /* sharp foreground: tight nodal strings, no wide halo */
    vec3 lineCol = sand * line * (0.95 + 1.70 * beat);
    lineCol += vec3(1.0) * pow(line, 3.0) * (0.35 + 0.50 * beat);
    lineCol += vec3(1.0) * 0.15 * snare * exp(-abs(f0) * 9.0);
    lineCol += vec3(0.9) * spark * line * 1.2;
    lineCol += hot * line * (0.22 + 0.45 * waveAmt) * (0.5 + 0.5 * wave);
    lineCol *= gInt;
    backCol *= gInt;

    /* centre bursts with inward trails: one per detected element */
    float ths = atan(qs.y, qs.x);
    float tk = nvBurst(rs, ths, kick, 1.10, 1.0, 18.0, 6.0, t * 0.7 + gCol * 6.0);
    float ts = nvBurst(rs, ths, snare, 1.25, 1.4, 24.0, 10.0, t * 1.1);
    float thb = nvBurst(rs, ths, hat, 1.45, 1.8, 30.0, 16.0, t * 1.7);
    float tv = nvBurst(rs, ths, vocal, 0.95, 0.7, 12.0, 4.0, t * 0.4);
    vec3 bursts = hot * tk * 0.60
                + vec3(1.0) * ts * 0.65
                + mix(gA, gB, 0.8) * thb * 0.40
                + mix(gA, gB, 0.3) * tv * 0.30;

    /* round plate: dark disc, faint rim, cover-tinted dark field */
    float plateMask = smoothstep(1.008, 0.992, rs);
    vec3 bg = vec3(0.004, 0.004, 0.006)
            + mix(gA, gB, 0.6) * 0.05 * exp(-length(uv) * 3.2);
    vec3 plate = vec3(0.012, 0.013, 0.016)
               + vec3(0.010) * nvNoise(q * 3.0 + 5.0)
               + vec3(0.008) * (1.0 - rs);
    plate *= 1.0 - 0.25 * gTaper * smoothstep(0.2, 1.0, rs);
    vec3 col = mix(bg, plate, plateMask);
    col += backCol * (0.55 + 0.45 * plateMask);   /* soft glow behind */
    col += backCol * (1.0 - plateMask) * 0.35;    /* spill outside the dish */
    col += lineCol * plateMask;                    /* sharp front on top */
    col += bursts * (0.45 + 0.20 * plateMask);     /* element bursts */

    /* coloured rim and a faint outer glow */
    col += mix(vec3(0.34, 0.32, 0.28), hot, 0.55) * exp(-abs(rs - 1.0) * 80.0) * 0.50;
    col += sand * 0.05 * exp(-abs(rs - 1.0) * 5.0);

    col *= 1.0 + 0.10 * beat;
    col *= 1.0 - 0.55 * smoothstep(0.65, 1.25, length(uv));
    c = vec4(col, 1.0);
}
