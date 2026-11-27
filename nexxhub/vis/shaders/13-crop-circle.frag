// Crop Circle — a vector crop formation seen from above.
// Grounded in the recorded construction language: rope-and-board compass
// geometry, nested rings, satellite circles, straight chords, a spiral
// flattened centre and a standing centre, in a straw field. Everything is
// drawn as crisp, anti-aliased signed-distance lines (no bloom): the field
// is straw/green, flattened crop darker, boundaries pale with a dark edge.
// Audio: bass expands the formation, mid grows the satellites, treble and
// the beat choose the rotational symmetry, the beat presses a new ring.
// nv:scale=0.45
//
vec3 hueShift(vec3 c, float a) {
    const vec3 k = vec3(0.57735027);
    float ca = cos(a);
    return c * ca + cross(k, c) * sin(a) + k * dot(k, c) * (1.0 - ca);
}
vec3 gA, gB;

float nvHash(float p) {
    return fract(sin(p * 127.1 + 311.7) * 43758.5453);
}

float nvNoise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = nvHash(dot(i, vec2(1.0, 57.0)));
    float b = nvHash(dot(i + vec2(1.0, 0.0), vec2(1.0, 57.0)));
    float c = nvHash(dot(i + vec2(0.0, 1.0), vec2(1.0, 57.0)));
    float d = nvHash(dot(i + vec2(1.0, 1.0), vec2(1.0, 57.0)));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

float sdCircle(vec2 p, vec2 c, float r) { return length(p - c) - r; }

float sdSeg(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / max(dot(ba, ba), 1e-6), 0.0, 1.0);
    return length(pa - ba * h);
}

/* Fibonacci number via Binet's formula (used for ring spacing/counts) */
float fibn(float k) {
    const float PHI = 1.61803399;
    return (pow(PHI, k) - pow(-PHI, -k)) * 0.44721360;
}

/* anti-aliased line: one global AA step, no fwidth per call */
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

    /* genome-driven parameters (self-learning GA) */
    float gBands = clamp(iGenomeA.y, 3.0, 10.0);
    float gDens  = clamp(iGenomeA.x / 120.0, 0.4, 1.8);
    float gZoom  = clamp(iGenomeB.z, 0.70, 1.30);
    float gBend  = clamp(iGenomeB.w, 0.0, 0.40);
    float gCol   = clamp(iGenomeB.y, 0.0, 1.0);
    float gInt   = clamp(iGenomeB.x, 0.70, 1.60);

    /* Lie algebra of the 2D similarity group, exponented per frame:
       J = rotation (so(2)), S = scaling (gl(1)), K = shear (sl(2)),
       T = translation (t(2)).  The golden log spiral later in the shader
       is the orbit of the S + iJ one-parameter subgroup. */
    float genJ = t * 0.012 + 0.20 * sin(t * 0.021) + 0.6 * (iEntropy.y - 0.5)
               + 0.30 * mid;
    float genS = 0.08 * sin(t * 0.037) + 0.10 * bass;
    float genK = 0.06 * sin(t * 0.031) + 0.08 * treb + 0.10 * gBend;
    vec2 q = uv / 0.62;
    q = mat2(cos(genJ), -sin(genJ), sin(genJ), cos(genJ)) * q;
    q *= exp(genS);
    q.x += genK * q.y;
    q += 0.020 * vec2(sin(t * 0.021), cos(t * 0.026));
    float r = length(q), th = atan(q.y, q.x);

    /* ---- straw field: rows, mottling, green edges ---- */
    float row = 0.5 + 0.5 * sin((q.x * 85.0 + q.y * 31.0)
                                + 2.5 * nvNoise(q * 3.5 + t * 0.015));
    vec3 field = mix(vec3(0.55, 0.42, 0.16), vec3(0.74, 0.60, 0.27), row);
    field = mix(field, vec3(0.26, 0.31, 0.12),
                smoothstep(0.72, 1.05, r) * 0.55);

    /* ---- formation parameters (audio + entropy) ---- */
    /* rotational symmetry snapped to the Fibonacci numbers 3/5/8 */
    /* rotational symmetry snapped to Fibonacci counts 3/5/8 */
    float ns = gBands + 3.0 * treb;
    float n = ns < 6.0 ? 3.0 : (ns < 9.0 ? 5.0 : 8.0);
    n = beat > 0.85 ? 8.0 : n;
    float R  = 0.52 + 0.10 * bass + 0.03 * sin(t * 0.021)
             + 0.035 * (gZoom - 1.0) + 0.02 * (iEntropy.x - 0.5);
    float rs = 0.085 + 0.045 * mid + 0.008 * sin(t * 0.031);
    float rv = 0.095 + 0.045 * (1.0 - bass);     /* standing centre */
    float satRot = t * 0.045 + 0.15 * beat + 0.8 * (iEntropy.z - 0.5);

    float line = 0.0, construct = 0.0;
    float flatArea = 1.0 - smoothstep(R + rs + 0.01, R + rs + 0.02, r);

    /* nested rings on Fibonacci fractions of the gap; count follows density */
    float gap = R - rv;
    int rings = 2 + int(floor(clamp(gDens * 1.6, 0.0, 2.9)));
    line = max(line, nvLine(sdCircle(q, vec2(0.0), rv), 0.0055));
    for (int k = 0; k < 4; k++) {
        if (k < rings) {
            float fk = fibn(float(k + 2));       /* 2, 3, 5, 8 */
            float rk = rv + gap * fk / 8.0;
            line = max(line, nvLine(sdCircle(q, vec2(0.0), rk), 0.0045));
        }
    }
    /* outer boundary ring of the flattened area */
    line = max(line, nvLine(sdCircle(q, vec2(0.0), R + rs), 0.006));

    /* satellite circles on the ring, each with its own radius */
    float satFlat = 0.0;
    for (int i = 0; i < 8; i++) {
        if (float(i) < n) {
            float fi = float(i);
            float ang = satRot + 6.2831853 * fi / n;
            vec2 cen = R * vec2(cos(ang), sin(ang));
            float rr = rs * (0.78 + 0.44 * fract(fi * 0.7548776 + 0.31));
            float d = sdCircle(q, cen, rr);
            line = max(line, nvLine(d, 0.005));
            satFlat = max(satFlat, 1.0 - smoothstep(rr - 0.004, rr + 0.004,
                                                    length(q - cen)));
            /* rope-and-board straight chord back to the centre */
            construct = max(construct,
                            nvLine(sdSeg(q, vec2(0.0), cen), 0.0022) * 0.32);
        }
    }

    /* Fibonacci word on the rim: s_i = floor((i+1)phi) - floor(i*phi),
       the Sturmian word generated by the golden ratio.  One tick per
       1/32 of a turn; the bit sets the tick length (a binary ring). */
    float cells = gCol > 0.5 ? 34.0 : 21.0;
    float angCell = (th + 3.14159265) / 6.2831853 * cells;
    float ci = floor(angCell);
    float cf = fract(angCell);
    float fbit = floor((ci + 1.0) * 1.61803399) - floor(ci * 1.61803399);
    float rTick = R + rs + 0.035;
    float tickLen = 0.010 + 0.018 * fbit;
    float tick = smoothstep(0.07, 0.0, abs(cf - 0.5))
               * smoothstep(0.004, 0.0, abs(r - (rTick + tickLen * 0.5)));
    line = max(line, tick);

    /* golden log spiral: r = a·e^(bθ), b = ln φ / (π/2) */
    float lnr = log(max(r, 0.02) / 0.02);
    float gphase = th - lnr / 0.3063489;
    float gd = abs(mod(gphase + 3.14159265, 6.2831853) - 3.14159265);
    float spiral = smoothstep(0.20, 0.0, gd)
                 * smoothstep(rv * 0.95, rv * 0.15, r);

    /* phyllotaxis seed head: golden-angle dots in the standing centre */
    float seeds = 0.0;
    for (int k = 0; k < 6; k++) {
        float fk = float(k) + 0.5;
        float rad = rv * 0.80 * sqrt(fk / 6.0);
        float ang = fk * 2.39996323 + t * 0.05;
        vec2 cen = rad * vec2(cos(ang), sin(ang));
        seeds = max(seeds, nvLine(sdCircle(q, cen, 0.0045
                                          + 0.0018 * sin(fk * 2.1)), 0.0018));
    }

    /* flattened crop: darker with a swirl of laid stalks */
    float flatMask = max(flatArea, satFlat) * smoothstep(rv * 0.92, rv, r);
    float swirl = 0.5 + 0.5 * sin(th * 7.0 + r * 55.0 - t * 0.30
                                   + 1.5 * nvNoise(q * 5.0))
                * (0.7 + 0.3 * sin(th * 13.0 - r * 28.0 + t * 0.18));
    vec3 flatc = mix(vec3(0.24, 0.20, 0.07), vec3(0.38, 0.31, 0.11), swirl);
    flatc *= 0.88 + 0.20 * nvNoise(q * 9.0 + 3.0);
    vec3 col = mix(field, flatc, flatMask * 0.94);

    /* vector boundaries: dark edge + pale straw highlight */
    float edge = nvLine(line, 0.010);
    col = mix(col, vec3(0.17, 0.13, 0.05), edge * 0.55);
    col = mix(col, vec3(0.95, 0.90, 0.67), clamp(line * 0.95 * gInt, 0.0, 1.0));
    col = mix(col, vec3(0.86, 0.80, 0.58), construct);
    col = mix(col, vec3(0.88, 0.80, 0.55), spiral * 0.60);
    col = mix(col, vec3(0.92, 0.86, 0.62), seeds * 0.55);

    /* standing centre: unflattened crop, slightly brighter */
    float centre = 1.0 - smoothstep(rv * 0.90, rv * 0.90 + 0.008, r);
    col = mix(col, field * 1.18, centre * 0.65);

    /* beat presses the formation: line flash and a faint new ring */
    col += vec3(0.95, 0.88, 0.62) * line * beat * 0.25;
    float press = exp(-abs(r - (0.20 + 0.55 * fract(iBeat.y))) * 60.0) * beat;
    col += vec3(0.90, 0.82, 0.55) * press * 0.25;

    col = mix(col, mix(gA, gB, gCol), 0.05 + 0.10 * gCol);   /* cover/genome tint */
    col *= 1.0 - 0.35 * smoothstep(0.70, 1.30, length(uv));
    c = vec4(col, 1.0);
}
