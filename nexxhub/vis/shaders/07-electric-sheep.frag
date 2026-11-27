// Electric Sheep — a real-time fractal-flame field after Scott Draves'
// flam3 genome. flam3 builds a flame from affine transforms, weighted
// variations (fold, inversion, sinusoidal, swirl) and a final transform,
// then colours it from a 256-entry palette with hue rotation. Here the
// folded/inverted orbit is evaluated per pixel and coloured by its orbit
// trap: a 4-fold symmetric fractal with glowing filaments, a cyclic palette
// (cover art -> per-track hue rotation), drifting genome offsets and audio
// as a mutation. Bass bends the genome, the beat flashes the trap and
// shifts the palette, so each drop breeds a new sheep.
// nv:scale=0.40
//
vec3 hueShift(vec3 c, float a) {
    const vec3 k = vec3(0.57735027);
    float ca = cos(a);
    return c * ca + cross(k, c) * sin(a) + k * dot(k, c) * (1.0 - ca);
}
vec3 gA, gB;

mat2 nvRot(float a) { float c = cos(a), s = sin(a); return mat2(c, -s, s, c); }

float nvHash(vec2 p) {
    return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
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

vec3 nvPal(float h) {
    h = fract(h);
    vec3 c = mix(gA, gB, smoothstep(0.0, 0.5, h));
    c = mix(c, gA, smoothstep(0.5, 1.0, h));
    c = mix(c, vec3(1.00, 0.55, 0.20),
            0.30 * pow(0.5 + 0.5 * sin(h * 6.2831853 + 1.7), 3.0));
    c += vec3(0.80) * pow(0.5 + 0.5 * sin(h * 6.2831853), 10.0);
    c = c * 1.30 + 0.05;                 /* keep dark cover palettes legible */
    return c;
}

void mainImage(out vec4 c, in vec2 p) {
    vec2 uv = (p - 0.5 * iResolution.xy) / iResolution.y;
    float t = iTime, bass = iLevel.x, beat = iBeat.x * iBeat.w;
    gA = hueShift(iCoverA, iHue);
    gB = hueShift(iCoverB, iHue);

    /* genome: slow rotation, scale and affine offset, mutated by audio */
    float ang = t * 0.030 + 0.20 * iGenomeA.w;
    vec2 q = nvRot(ang) * (uv * (2.35 + 0.55 * iGenomeA.z));
    vec2 c0 = vec2(0.52 + 0.05 * sin(t * 0.11),
                   0.30 + 0.05 * cos(t * 0.13));
    c0 += 0.10 * bass * vec2(sin(t * 0.70), cos(t * 0.61));
    c0 += 0.05 * beat * vec2(1.0, -0.6);

    /* folded inversion + sinusoidal variation: the flame's chaotic orbit */
    float trap = 1e9, trap2 = 1e9;
    for (int i = 0; i < 12; i++) {
        q = abs(q);
        q = q / max(dot(q, q), 0.04) - c0;
        q += 0.10 * vec2(sin(q.y * 2.7 + t * 0.21),
                         sin(q.x * 3.1 - t * 0.18));
        q = nvRot(0.004 + 0.06 * sin(t * 0.05)) * q;
        q *= 1.004;
        trap = min(trap, length(q));
        trap2 = min(trap2, length(q - vec2(0.7, 0.2)));
    }

    /* depth shading: the flame emerges from a smoky dark field */
    float shade = 0.42 + 0.58 * smoothstep(0.08, 0.90,
                     nvNoise(uv * 1.8 + vec2(t * 0.013, -t * 0.011)));
    float h = fract(trap * 1.35 + 0.10 * t + 0.10 * length(uv));
    vec3 pal = nvPal(h);
    pal *= 0.85 + 0.30 * pal;            /* push saturation, keep darks */
    float glow = exp(-trap * 6.5);
    vec3 col = pal * glow * (0.80 + 1.50 * beat) * shade;
    col += pal * 0.10 * smoothstep(0.75, 0.0, trap) * shade;
    col += nvPal(fract(h + 0.5)) * exp(-trap2 * 8.0) * 0.22;
    col += vec3(1.0, 0.96, 0.90) * pow(glow, 4.0) * 0.35;
    col += vec3(0.25, 0.75, 1.0) * pow(glow, 3.0) * 0.15;      /* electric sheen */
    col += mix(gA, gB, 0.5) * 0.06 * exp(-length(uv) * 3.0);   /* core */

    /* dim nebula behind the flame, as in the sheep's dark field */
    float haze = nvNoise(uv * 3.2 + vec2(t * 0.02, -t * 0.015));
    col += mix(gA, gB, haze) * 0.018 * haze;

    col *= 0.55 + 0.45 * smoothstep(1.05, 0.05, length(uv));
    col *= 1.0 + 0.10 * beat;
    col *= 1.0 - 0.55 * smoothstep(0.60, 1.25, length(uv));
    c = vec4(col, 1.0);
}
