// Aurora curtains: flowing noise bands lit by the spectrum; bass lifts brightness, treble shifts hue.
// Tuned for the Pi 4 GPU: all noise is 1-D in x (curtains only move sideways), rendered at 1/3 scale.
// nv:scale=0.25
float spec(float x) { return texture(iChannel0, vec2(clamp(x, 0.0, 1.0), 0.25)).r; }

float hash1(float n) { n = fract(n * 0.1031); n *= n + 33.33; n *= n + n; return fract(n); }
float hash(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}
float noise1(float x) {
    float i = floor(x), f = fract(x);
    return mix(hash1(i), hash1(i + 1.0), f * f * (3.0 - 2.0 * f));
}
float fbm1(float x) {
    return (0.5 * noise1(x) + 0.25 * noise1(x * 2.03 + 1.7) + 0.125 * noise1(x * 4.12 + 5.3)) / 0.875;
}

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 uv = fragCoord / iResolution.xy;
    float t = iTime * 0.05;
    float bass = iLevel.x, mid = iLevel.y, treb = iLevel.z;
    float beat = iBeat.x * iBeat.w;

    vec3 col = mix(vec3(0.01, 0.015, 0.04), vec3(0.03, 0.02, 0.08), uv.y);
    // stars
    vec2 cell = floor(fragCoord / 3.0);
    float h = hash(cell);
    col += step(0.997, h) * (0.5 + 0.5 * fract(iTime * 0.7 + h * 13.0)) * 0.5;

    for (int k = 0; k < 3; k++) {
        float fk = float(k);
        float base = 0.42 + 0.14 * fk + 0.06 * sin(t * 3.0 + fk * 2.1) + 0.02 * beat;
        float warp = fbm1(uv.x * 2.5 + t * (1.0 + fk * 0.4) + fk * 31.7);
        float y = base + (warp - 0.5) * 0.35;
        float d = uv.y - y;
        if (d < -0.02) continue;                       // below this curtain: nothing to add
        float band = spec(uv.x * 0.7 + 0.05 + fk * 0.08);
        float curtain = exp(-d * (9.0 - 4.0 * band)) * smoothstep(-0.02, 0.0, d);
        float rays = 0.6 + 0.4 * noise1(uv.x * 30.0 + warp * 4.0 + t * 6.0 + fk * 57.0);
        float hue = fk * 0.18 + treb * 0.25 + 0.05 * sin(t * 2.0);
        vec3 c = 0.5 + 0.5 * cos(6.2831 * (hue + vec3(0.30, 0.55, 0.85)));
        col += c * curtain * rays * (0.25 + 1.2 * band + 0.8 * bass) * (0.55 - 0.12 * fk);
    }
    // horizon glow follows the low-mid energy
    col += vec3(0.1, 0.3, 0.5) * exp(-uv.y * 9.0) * (0.15 + mid);
    col = 1.0 - exp(-col * 1.4);
    col *= 1.0 + 0.10 * beat;
    fragColor = vec4(col, 1.0);
}
