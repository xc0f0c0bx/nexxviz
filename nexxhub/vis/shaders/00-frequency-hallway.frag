// Frequency Hallway — flat stacked spectrum wall, variant-5 structure.
// Native GLSL for nexxvis (not the vizz.fm app). 420 thin bars across x, six
// Y copies via domain repetition, two Z scales, lens-tapered vertical
// ribbons, four-way mirror and cover palette. The beat bends the rows on Y
// from the centre outward.
// nv:scale=0.65
//
float nvSpec(float x) {
    return texture(iChannel0, vec2(clamp(x, 0.0, 1.0), 0.25)).r;
}

vec3 hueShift(vec3 c, float a) {
    const vec3 k = vec3(0.57735027);
    float ca = cos(a);
    return c * ca + cross(k, c) * sin(a) + k * dot(k, c) * (1.0 - ca);
}
vec3 gA, gB;   /* cover palette after the per-track hue rotation */

vec3 nvRibbons(vec2 q, float t, float bass, float beat, float scale, float gain) {
    /* the genome: density, bands, taper, glow, intensity, colour, z, bend */
    float density = iGenomeA.x, bands = iGenomeA.y;
    float taper = iGenomeA.z, glowAmt = iGenomeA.w;
    float intensityAmt = iGenomeB.x, colorMix = iGenomeB.y, bendAmt = iGenomeB.w;

    vec2 g = q / scale;
    /* elliptical warp centred on the inside: the displacement follows an
     * ellipse (x/y radii 1.35/0.72), affects the interior too, and grows
     * outward with a wave travelling from the centre. */
    vec2 e = vec2(g.x / 1.35, g.y / 0.72);
    float er = length(e);
    float bend = (beat * bendAmt + 0.02) * (0.30 + 0.70 * min(er, 1.5))
               * sin(er * 5.0 - t * 2.0);
    vec2 dir = e / max(er, 1e-4);
    g += vec2(dir.x * 1.35, dir.y * 0.72) * bend * 0.22;

    float env = exp(-pow(g.y / (taper * scale), 2.0));   /* lens taper */

    float fx = clamp(g.x * 1.25, 0.0, 1.0);
    float raw = nvSpec(pow(fx, 0.80) * 0.78 + 0.02);
    float loud = clamp(0.30 + 0.70 * (bass * 0.5 + iLevel.w * 0.5), 0.25, 1.0);
    float s = pow(clamp(raw / loud, 0.0, 1.0), 1.15);

    float bf = fract(g.x * density);
    float gap = smoothstep(0.0, 0.25, bf) * smoothstep(1.0, 0.75, bf);
    float band = 0.42 + 0.58 * pow(0.5 + 0.5 * cos(g.y * bands * 6.2831 + t * 1.6), 2.0);

    float intensity = gap * env * band * (0.30 + 1.10 * s) * (0.65 + 0.40 * glowAmt);
    float warm = clamp((bass - iLevel.z) / (bass + iLevel.z + 0.05), -1.0, 1.0);
    vec3 temp = vec3(1.0 + 0.40 * warm, 1.0 - 0.08 * abs(warm), 1.0 - 0.40 * warm);
    vec3 body = mix(gA * 0.70, gB * 0.95, clamp(s * colorMix, 0.0, 1.0)) * temp;
    return body * intensity * gain * (0.80 + 0.45 * s) * intensityAmt * 0.90;
}

void mainImage(out vec4 c, in vec2 p) {
    vec2 uv = (p - 0.5 * iResolution.xy) / iResolution.y;
    vec2 q = abs(uv);                 /* four-way mirror */
    /* per-track colourisation: a new hue rotation on every track switch */
    gA = hueShift(iCoverA, iHue);
    gB = hueShift(iCoverB, iHue);
    float t = iTime, bass = iLevel.x, beat = iBeat.x * iBeat.w;

    vec3 col = nvRibbons(q, t, bass, beat, 1.00, 1.00);
    col += nvRibbons(q, t, bass, beat, iGenomeB.z, 0.30);   /* second Z copy */

    float warm = clamp((bass - iLevel.z) / (bass + iLevel.z + 0.05), -1.0, 1.0);
    vec3 temp = vec3(1.0 + 0.40 * warm, 1.0 - 0.08 * abs(warm), 1.0 - 0.40 * warm);
    vec3 eye = mix(gA, gB, 0.5) * temp;
    col += eye * exp(-length(vec2(q.x * 22.0, q.y * 70.0)))
         * (0.18 + 0.35 * bass + 0.20 * beat);
    col += mix(iCoverA, eye, 0.5) * exp(-q.y * 80.0) * (0.08 + 0.20 * bass);

    col *= 1.0 + 0.12 * beat;            /* punch on the beat */
    col *= 1.0 - 0.45 * smoothstep(0.55, 1.20, length(uv));
    c = vec4(col, 1.0);
}
