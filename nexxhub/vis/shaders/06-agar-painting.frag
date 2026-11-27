// Agar Painting — bacterial colonies growing on a dark agar dish, after the
// agar-art pieces of Maria Peñil Cobo and Dr. Mehmet Berkmen ("Neurons").
// Top-down petri dish: a Voronoi field of glossy colonies in a bacterial
// palette (gold, orange, coral, cream, teal, lavender), a thin golden
// filament network on the agar, condensation specks and a glass rim.
// Bass swells the colonies, the beat pulses their glow, and a slow wave
// crosses the dish.
// nv:scale=0.45
//
vec2 nvHash2(vec2 p) {
    p = vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)));
    return fract(sin(p) * 43758.5453);
}

float nvHash1(vec2 p) {
    return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}

float nvNoise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = nvHash1(i);
    float b = nvHash1(i + vec2(1.0, 0.0));
    float c = nvHash1(i + vec2(0.0, 1.0));
    float d = nvHash1(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

vec3 nvPal(float h) {
    h = fract(h);
    vec3 c = mix(vec3(0.95, 0.80, 0.28), vec3(0.95, 0.45, 0.18), smoothstep(0.00, 0.20, h));
    c = mix(c, vec3(0.88, 0.25, 0.42), smoothstep(0.20, 0.40, h));
    c = mix(c, vec3(0.86, 0.86, 0.70), smoothstep(0.40, 0.60, h));
    c = mix(c, vec3(0.28, 0.66, 0.58), smoothstep(0.60, 0.80, h));
    c = mix(c, vec3(0.62, 0.42, 0.82), smoothstep(0.80, 1.00, h));
    return c;
}

void nvVor(vec2 p, out float f1, out float f2, out vec2 cid, out vec2 cpos) {
    vec2 n = floor(p), f = fract(p);
    f1 = 8.0; f2 = 8.0; cid = vec2(0.0); cpos = vec2(0.0);
    for (int j = -1; j <= 1; j++)
    for (int i = -1; i <= 1; i++) {
        vec2 g = vec2(float(i), float(j));
        vec2 o = nvHash2(n + g);
        vec2 r = g + o - f;
        float dd = dot(r, r);
        if (dd < f1) { f2 = f1; f1 = dd; cid = n + g; cpos = n + g + o; }
        else if (dd < f2) f2 = dd;
    }
    f1 = sqrt(f1); f2 = sqrt(f2);
}

/* one colony field; returns rgb and coverage via w */
vec4 nvColonies(vec2 d, float t, float bass, float beat, float seed, float S,
                float rmin, float rmax, out float of1, out float of2) {
    float f1, f2; vec2 cid, cpos;
    nvVor(d * S + seed, f1, f2, cid, cpos);
    of1 = f1; of2 = f2;
    vec2 off = d * S + seed - cpos;
    float hsh = nvHash1(cid + seed);
    float grow = 0.92 + 0.08 * sin(t * 0.35 + hsh * 6.28) + 0.25 * bass + 0.10 * beat;
    float R = (rmin + (rmax - rmin) * nvHash1(cid + seed + 3.0)) * grow;
    float nEdge = nvNoise(off * 7.0 + cid * 13.0);
    float rr = length(off) / max(R * (0.92 + 0.16 * nEdge), 1e-4);
    float cov = smoothstep(1.0, 0.90, rr);
    float dome = sqrt(max(0.0, 1.0 - rr * rr));
    vec3 nrm = normalize(vec3(-off / max(R, 1e-4) * 0.9, dome * 1.3));
    vec3 L = normalize(vec3(-0.45, 0.55, 0.75));
    float diff = clamp(dot(nrm, L), 0.0, 1.0);
    float hue = 0.50 + 0.34 * sin(d.x * 2.3 + d.y * 1.7)
              + 0.18 * (hsh - 0.5);
    vec3 pal = nvPal(hue);
    float rings = 0.92 + 0.08 * sin(rr * 16.0 + hsh * 9.0);
    vec3 ccol = pal * (0.38 + 0.90 * diff) * rings;
    ccol += vec3(1.0) * pow(max(dot(reflect(-L, nrm), vec3(0.0, 0.0, 1.0)), 0.0), 18.0) * 0.22;
    ccol += pal * (0.18 + 0.25 * beat) * dome;
    return vec4(ccol, cov);
}

void mainImage(out vec4 c, in vec2 p) {
    vec2 uv = (p - 0.5 * iResolution.xy) / iResolution.y;
    float t = iTime, bass = iLevel.x, beat = iBeat.x * iBeat.w;
    vec2 d = uv / 0.62;
    float r = length(d);

    vec3 col = vec3(0.004, 0.003, 0.004);
    if (r < 1.03) {
        /* dark agar with slow mottling and a soft overhead light */
        float ag = nvNoise(d * 4.0 + 3.0);
        vec3 agar = mix(vec3(0.022, 0.017, 0.012), vec3(0.085, 0.060, 0.033), ag);
        agar *= 0.65 + 0.75 * exp(-r * r * 1.6);
        agar += vec3(0.05, 0.035, 0.018) * nvNoise(d * 11.0 + 7.0) * 0.5;
        col = agar;

        /* golden filament network: the edges of the big-colony Voronoi */
        float bf1, bf2;
        vec4 big = nvColonies(d, t, bass, beat, 0.0, 6.5, 0.16, 0.30, bf1, bf2);
        float edge = smoothstep(0.16, 0.0, bf2 - bf1);
        float blotch = smoothstep(0.42, 0.70, nvNoise(d * 3.2 + 11.0 + t * 0.02));
        col += vec3(0.95, 0.62, 0.24) * edge * blotch * (0.20 + 0.30 * beat);

        /* large colonies */
        col = mix(col, big.rgb, big.a);

        /* small satellite colonies between the big ones */
        float sf1, sf2;
        vec4 sm = nvColonies(d, t * 0.9, bass, beat, 37.0, 14.0, 0.09, 0.16, sf1, sf2);
        col = mix(col, sm.rgb, sm.a * (1.0 - big.a) * 0.9);

        /* condensation and dust near the rim */
        vec2 gc = floor(uv * 48.0);
        vec2 go = fract(uv * 48.0) - 0.5;
        float gh = nvHash1(gc + 5.0);
        float drop = smoothstep(0.16, 0.04, length(go)) * step(0.955, gh)
                   * smoothstep(0.72, 0.90, r);
        col += vec3(0.55, 0.55, 0.58) * drop * 0.5;

        /* slow wave crossing the dish on the beat */
        float wave = exp(-pow((r - fract(t * 0.11) * 1.05) * 7.0, 2.0));
        col += vec3(1.0, 0.70, 0.30) * wave * 0.08 * (0.3 + beat);

        /* glass rim */
        col += vec3(0.40, 0.38, 0.32) * exp(-abs(r - 1.0) * 70.0) * 0.55;
        col += vec3(0.16, 0.15, 0.12) * exp(-abs(r - 0.955) * 120.0) * 0.40;
    }

    col *= 1.0 - 0.35 * smoothstep(0.80, 1.24, length(uv));
    c = vec4(col, 1.0);
}
