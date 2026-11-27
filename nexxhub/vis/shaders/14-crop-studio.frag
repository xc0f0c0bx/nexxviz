// Crop Studio — a sacred-geometry design platform.
// The canvas holds the Seed of Life (7 circles), a Flower of Life ring,
// Metatron's hexagram chords, a golden log spiral, a Fibonacci-word ring
// and phyllotaxis seeds. The studio shell adds a layer panel with live
// sliders, a tab bar and a spectrum strip. All vector SDFs, no bloom.
// nv:scale=0.45
//
vec3 hueShift(vec3 c, float a) {
    const vec3 k = vec3(0.57735027);
    float ca = cos(a);
    return c * ca + cross(k, c) * sin(a) + k * dot(k, c) * (1.0 - ca);
}
vec3 gA, gB;

float nvHash(float p) { return fract(sin(p * 127.1 + 311.7) * 43758.5453); }

float sdCircle(vec2 p, vec2 c, float r) { return length(p - c) - r; }

float sdSeg(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / max(dot(ba, ba), 1e-6), 0.0, 1.0);
    return length(pa - ba * h);
}

float sdBox(vec2 p, vec2 c, vec2 h, float r) {
    vec2 d = abs(p - c) - h + r;
    return length(max(d, 0.0)) + min(max(d.x, d.y), 0.0) - r;
}

float nvAA = 0.0016;
float nvLine(float d, float w) {
    return 1.0 - smoothstep(w, w + nvAA, abs(d));
}

void mainImage(out vec4 c, in vec2 p) {
    vec2 uv = (p - 0.5 * iResolution.xy) / iResolution.y;
    float t = iTime, bass = iLevel.x, mid = iLevel.y, treb = iLevel.z;
    float beat = iBeat.x * iBeat.w;
    gA = hueShift(iCoverA, iHue);
    gB = hueShift(iCoverB, iHue);

    float gBands = clamp(iGenomeA.y, 3.0, 10.0);
    float gBend  = clamp(iGenomeB.w, 0.0, 0.40);
    float gCol   = clamp(iGenomeB.y, 0.0, 1.0);
    float gInt   = clamp(iGenomeB.x, 0.70, 1.60);

    const vec3 CYAN  = vec3(0.28, 0.78, 0.92);
    const vec3 AMBER = vec3(0.96, 0.73, 0.33);
    const vec3 GOLD  = vec3(0.85, 0.66, 0.25);
    const vec3 TEXT  = vec3(0.52, 0.66, 0.74);

    /* ---- studio shell ---- */
    vec3 col = vec3(0.022, 0.030, 0.040);
    vec2 gc = fract(uv * vec2(26.0, 15.0)) - 0.5;
    float grid = max(1.0 - smoothstep(0.0, 0.035, abs(gc.x)),
                     1.0 - smoothstep(0.0, 0.035, abs(gc.y)));
    col += vec3(0.05, 0.09, 0.11) * grid * 0.35;

    float panelL = sdBox(uv, vec2(-0.80, 0.00), vec2(0.095, 0.440), 0.012);
    float panelT = sdBox(uv, vec2(0.00, 0.472), vec2(0.890, 0.024), 0.006);
    float panelB = sdBox(uv, vec2(0.00, -0.472), vec2(0.890, 0.024), 0.006);
    float canvas = sdBox(uv, vec2(0.09, 0.00), vec2(0.755, 0.420), 0.018);

    col = mix(col, vec3(0.050, 0.070, 0.092),
              (1.0 - smoothstep(-0.002, 0.002, panelL)) * 0.9);
    col = mix(col, vec3(0.050, 0.070, 0.092),
              (1.0 - smoothstep(-0.002, 0.002, panelT)) * 0.9);
    col = mix(col, vec3(0.050, 0.070, 0.092),
              (1.0 - smoothstep(-0.002, 0.002, panelB)) * 0.9);
    col = mix(col, vec3(0.030, 0.045, 0.058),
              (1.0 - smoothstep(-0.002, 0.002, canvas)) * 0.9);
    col += vec3(0.12, 0.20, 0.25) * nvLine(panelL, 0.0016) * 0.6;
    col += vec3(0.12, 0.20, 0.25) * nvLine(panelT, 0.0016) * 0.6;
    col += vec3(0.12, 0.20, 0.25) * nvLine(panelB, 0.0016) * 0.6;
    col += CYAN * nvLine(canvas, 0.0018) * 0.55;

    vec2 cg = fract(uv * vec2(34.0, 20.0)) - 0.5;
    float cgrid = max(1.0 - smoothstep(0.0, 0.03, abs(cg.x)),
                      1.0 - smoothstep(0.0, 0.03, abs(cg.y)));
    col += vec3(0.07, 0.11, 0.14) * cgrid
         * (1.0 - smoothstep(-0.002, 0.002, canvas)) * 0.5;

    /* ---- sacred geometry inside the canvas ---- */
    vec2 q = (uv - vec2(0.09, 0.0)) / 0.56;
    float genJ = t * 0.02 + 0.25 * mid + 0.6 * (iEntropy.y - 0.5);
    float genK = 0.05 * sin(t * 0.031) + 0.06 * treb + 0.08 * gBend;
    q = mat2(cos(genJ), -sin(genJ), sin(genJ), cos(genJ)) * q;
    q.x += genK * q.y;
    float r = length(q), th = atan(q.y, q.x);
    float cmask = 1.0 - smoothstep(-0.002, 0.002, canvas);

    float a = 0.145 + 0.035 * bass;            /* circle radius */
    float circles = 0.0, chords = 0.0;

    /* Seed of Life: centre + six circles */
    circles = max(circles, nvLine(sdCircle(q, vec2(0.0), a), 0.0018));
    for (int i = 0; i < 6; i++) {
        float ang = 6.2831853 * float(i) / 6.0;
        vec2 c1 = a * vec2(cos(ang), sin(ang));
        circles = max(circles, nvLine(sdCircle(q, c1, a), 0.0018));
        chords = max(chords, nvLine(sdSeg(q, vec2(0.0), c1), 0.0011) * 0.45);
        /* Flower of Life second ring */
        vec2 c2 = 2.0 * a * vec2(cos(ang), sin(ang));
        circles = max(circles, nvLine(sdCircle(q, c2, a), 0.0014) * 0.75);
        /* Metatron chords to the outer ring */
        chords = max(chords, nvLine(sdSeg(q, vec2(0.0), c2), 0.0009) * 0.28);
    }

    /* outer vesica circle and hexagram (two triangles on radius 2a) */
    circles = max(circles, nvLine(sdCircle(q, vec2(0.0), 2.0 * a), 0.0016));
    for (int i = 0; i < 3; i++) {
        float a0 = 6.2831853 * float(i) / 3.0 + 1.5707963;
        float a1 = 6.2831853 * (float(i) + 1.0) / 3.0 + 1.5707963;
        vec2 v0 = 2.0 * a * vec2(cos(a0), sin(a0));
        vec2 v1 = 2.0 * a * vec2(cos(a1), sin(a1));
        chords = max(chords, nvLine(sdSeg(q, v0, v1), 0.0013) * 0.55);
        vec2 u0 = 2.0 * a * vec2(cos(a0 + 3.1415926), sin(a0 + 3.1415926));
        vec2 u1 = 2.0 * a * vec2(cos(a1 + 3.1415926), sin(a1 + 3.1415926));
        chords = max(chords, nvLine(sdSeg(q, u0, u1), 0.0013) * 0.55);
    }

    /* golden log spiral inside the Seed */
    float lnr = log(max(r, 0.015) / 0.015);
    float gd = abs(mod(th - lnr / 0.3063489 + 3.14159265, 6.2831853)
                   - 3.14159265);
    float spiral = smoothstep(0.20, 0.0, gd) * smoothstep(2.0 * a, a * 0.15, r);

    /* Fibonacci-word ring around the Flower */
    float cells = gCol > 0.5 ? 34.0 : 21.0;
    float angCell = (th + 3.14159265) / 6.2831853 * cells;
    float ci = floor(angCell), cf = fract(angCell);
    float fbit = floor((ci + 1.0) * 1.61803399) - floor(ci * 1.61803399);
    float rTick = 2.0 * a + 0.035;
    float tick = smoothstep(0.07, 0.0, abs(cf - 0.5))
               * smoothstep(0.004, 0.0, abs(r - (rTick + 0.008 + 0.014 * fbit)));

    /* phyllotaxis seeds in the Seed centre */
    float seeds = 0.0;
    for (int k = 0; k < 6; k++) {
        float fk = float(k) + 0.5;
        float rad = a * 0.55 * sqrt(fk / 6.0);
        float ang = fk * 2.39996323 + t * 0.05;
        seeds = max(seeds, nvLine(sdCircle(q, rad * vec2(cos(ang), sin(ang)),
                                          0.0032), 0.0015));
    }

    col += AMBER * circles * cmask * gInt;
    col += CYAN * chords * cmask;
    col += GOLD * spiral * cmask * 0.7;
    col += CYAN * (tick * 0.8 + seeds) * cmask;
    col += CYAN * 0.20 * beat * exp(-abs(r - 0.10 - 0.55 * fract(iBeat.y)) * 60.0)
         * cmask;

    /* ---- UI: layer panel with sliders ---- */
    float uiL = 0.0;
    for (int i = 0; i < 3; i++) {
        float y = 0.30 - 0.13 * float(i);
        float val = i == 0 ? bass : (i == 1 ? mid : treb);
        uiL = max(uiL, nvLine(sdSeg(uv, vec2(-0.87, y), vec2(-0.73, y)), 0.0018));
        uiL = max(uiL, nvLine(sdCircle(uv, vec2(-0.87 + 0.14 * val, y), 0.0075), 0.0032));
        uiL = max(uiL, nvLine(sdSeg(uv, vec2(-0.87, y - 0.035),
                                   vec2(-0.87 + 0.06, y - 0.035)), 0.0022));
    }
    for (int i = 0; i < 3; i++) {
        float y = -0.14 - 0.10 * float(i);
        uiL = max(uiL, nvLine(sdSeg(uv, vec2(-0.82, y), vec2(-0.73, y)), 0.0018));
    }
    col += TEXT * uiL * 0.55;
    col += CYAN * nvLine(sdBox(uv, vec2(-0.85, -0.14), vec2(0.012, 0.012), 0.003), 0.0016) * 0.8;
    col += AMBER * nvLine(sdBox(uv, vec2(-0.85, -0.24), vec2(0.012, 0.012), 0.003), 0.0016) * 0.8;
    col += GOLD * nvLine(sdBox(uv, vec2(-0.85, -0.34), vec2(0.012, 0.012), 0.003), 0.0016) * 0.8;

    for (int i = 0; i < 3; i++) {
        float x = -0.80 + 0.14 * float(i);
        float tab = nvLine(sdBox(uv, vec2(x, 0.472), vec2(0.055, 0.012), 0.004), 0.0014);
        col += (i == 0 ? AMBER : TEXT) * tab * 0.6;
    }
    float live = nvLine(sdCircle(uv, vec2(0.84, 0.472), 0.007), 0.003);
    col += AMBER * live * (0.35 + 0.65 * beat);

    for (int i = 0; i < 8; i++) {
        float v = i < 4 ? iBandA[i] : iBandB[i - 4];
        float x = -0.62 + 0.075 * float(i);
        float h = 0.008 + 0.025 * v;
        col += CYAN * nvLine(sdBox(uv, vec2(x, -0.472), vec2(0.024, h), 0.002), 0.0012) * 0.7;
    }

    col *= 1.0 - 0.30 * smoothstep(0.70, 1.30, length(uv));
    c = vec4(col, 1.0);
}
