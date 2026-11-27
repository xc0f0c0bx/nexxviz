// Cymatics — an extended modal model on top of the v1 look.
// The plate is driven by three superimposed Chladni modes (base, mid and
// treble), each with a decaying beat envelope so the higher modes ring after
// a hit. The base mode also supplies its analytic gradient: a fine core line
// is drawn at the physical distance |f|/|∇f|, and the sand grain is advected
// along the gradient as the plate vibrates. The v1 continuous warping,
// phase shift, warm sand, sparkles and dark plate are preserved.
// nv:scale=0.65
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

float nvChladni(vec2 q, float n, float m, float ph) {
    const float PI = 3.14159265;
    return cos(n * PI * q.x + ph) * cos(m * PI * q.y - ph)
         - cos(m * PI * q.x - ph) * cos(n * PI * q.y + ph);
}

/* field plus analytic gradient: (f, df/dx, df/dy) */
vec3 nvChladniG(vec2 q, float n, float m, float ph) {
    const float PI = 3.14159265;
    float c1 = cos(n * PI * q.x + ph), s1 = sin(n * PI * q.x + ph);
    float c2 = cos(m * PI * q.y - ph), s2 = sin(m * PI * q.y - ph);
    float c3 = cos(m * PI * q.x - ph), s3 = sin(m * PI * q.x - ph);
    float c4 = cos(n * PI * q.y + ph), s4 = sin(n * PI * q.y + ph);
    return vec3(c1 * c2 - c3 * c4,
                -n * PI * s1 * c2 + m * PI * s3 * c4,
                -m * PI * c1 * s2 + n * PI * c3 * s4);
}

void mainImage(out vec4 c, in vec2 p) {
    vec2 uv = (p - 0.5 * iResolution.xy) / iResolution.y;
    float t = iTime, bass = iLevel.x, mid = iLevel.y, treb = iLevel.z;
    float beat = iBeat.x * iBeat.w;
    float phase = iBeat.y;          /* 0..1 between beats */
    float e0 = iEntropy.x, e1 = iEntropy.y, e2 = iEntropy.z, e3 = iEntropy.w;
    gA = hueShift(iCoverA, iHue);
    gB = hueShift(iCoverB, iHue);

    /* genetic variation (evolve.py): density, bands, taper, glow,
       intensity, colour, zoom, bend */
    float gDens  = clamp(iGenomeA.x / 120.0, 0.35, 2.0);
    float gBands = clamp(iGenomeA.y, 3.0, 8.0);
    float gTaper = clamp(iGenomeA.z, 0.20, 0.90);
    float gGlow  = clamp(iGenomeA.w, 0.10, 0.90);
    float gInt   = clamp(iGenomeB.x, 0.70, 1.70);
    float gCol   = clamp(iGenomeB.y, 0.00, 1.00);
    float gZoom  = clamp(iGenomeB.z, 0.65, 1.35);
    float gBend  = clamp(iGenomeB.w, 0.00, 0.45);

    /* plate coordinates; the beat gives the sand a small tremor */
    vec2 q = uv / (0.55 * gZoom);
    q += 0.006 * beat * vec2(sin(t * 57.0), cos(t * 49.0));
    q += 0.002 * vec2(sin(t * 11.0 + q.y * 8.0), cos(t * 9.0 + q.x * 8.0));
    q += gBend * 0.015 * vec2(sin(q.y * 3.1 + t * 0.35),
                              cos(q.x * 2.9 - t * 0.31));

    /* modal set: base, mid and treble Chladni modes, bent by the genome */
    float n = 3.0 + 4.5 * bass + 0.9 * sin(t * 0.11);
    n *= 0.85 + 0.15 * gDens;
    float m = 4.0 + 3.5 * treb + 0.9 * cos(t * 0.09);
    m = 2.0 + (m - 2.0) * (0.85 + 0.15 * gDens);
    float ph = (0.28 + 0.20 * gBend) * beat + 0.15 * gBend * sin(t * 0.10)
             + 0.16 * (e2 - 0.5);

    vec3 G = nvChladniG(q, n, m, ph);
    float f0 = G.x;
    float f1 = nvChladni(q, n + 1.2 + 0.5 * mid + 0.25 * gBands, m + 1.0, -0.5 * ph);
    float f2 = nvChladni(q, n + 2.5 + 0.20 * gBands, m + 1.5, 0.8 * ph + 0.4 * beat);

    /* band weights; higher modes ring after the beat */
    float env = exp(-phase * 3.2);
    float w1 = (0.30 + 0.55 * mid) * (0.55 + 0.45 * env);
    float w2 = (0.10 + 0.45 * treb) * (0.30 + 0.70 * env);
    float W = 1.0 + w1 + w2;

    /* v1 line stack, now a weighted modal sum */
    float core = (exp(-abs(f0) * 32.0)
                + w1 * exp(-abs(f1) * 34.0)
                + w2 * exp(-abs(f2) * 30.0)) / W;
    float halo = (exp(-abs(f0) * 9.0) + w1 * exp(-abs(f1) * 10.0)) / W;

    /* physical core: distance to the base nodal set, uniform width */
    float dp = abs(G.x) / (length(G.yz) + 1e-3);
    core += exp(-dp * 420.0) * 0.25;

    /* sand grain, advected along the gradient on the beat */
    vec2 go = G.yz / (length(G.yz) + 1e-4) * 0.0018 * (0.4 + beat);
    float grain = nvHash(floor((uv + go + vec2(e3, e1) * 2.0) * 430.0));
    float spark = smoothstep(0.975, 1.0, grain);
    vec3 sand = mix(vec3(0.96, 0.88, 0.70), mix(gA, gB, gCol),
                    0.12 + 0.30 * gCol);
    sand *= 0.78 + 0.34 * grain;

    vec3 sandcol = sand * (core * (0.65 + 1.25 * beat)
                           + halo * (0.10 + 0.25 * gGlow));
    sandcol += vec3(0.9) * spark * core * 1.6;
    sandcol += mix(gA, gB, 0.5) * halo * 0.03 * (0.5 + beat);
    sandcol *= gInt;

    /* dark anodised plate; only a trace of topography from the base mode */
    float rq = max(abs(q.x), abs(q.y));
    float plateMask = smoothstep(1.012, 0.992, rq);
    vec3 bg = vec3(0.004, 0.004, 0.006)
            + mix(gA, gB, 0.6) * 0.05 * exp(-length(uv) * 3.2);
    vec3 plate = vec3(0.020, 0.022, 0.026)
               + vec3(0.012) * nvNoise(q * 3.0 + 5.0)
               + vec3(0.010) * (1.0 - rq);
    plate *= 1.0 + 0.025 * f0 * env;
    plate *= 1.0 - 0.25 * gTaper * smoothstep(0.2, 1.0, rq);
    vec3 col = mix(bg, plate, plateMask);
    col += sandcol * plateMask;

    col += vec3(0.30, 0.28, 0.24) * exp(-abs(rq - 1.0) * 70.0)
         * (0.55 + 0.45 * max(0.0, -q.y));
    col += sand * 0.045 * exp(-abs(rq - 1.0) * 5.0);

    col *= 1.0 + 0.10 * beat;
    col *= 1.0 - 0.45 * smoothstep(0.70, 1.30, length(uv));
    c = vec4(col, 1.0);
}
