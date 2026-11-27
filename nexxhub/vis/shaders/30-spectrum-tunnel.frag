// Spectrum tunnel: rings rush toward the viewer; each ring's brightness is a spectrum band, speed follows energy.
// nv:scale=0.5
float spec(float x) { return texture(iChannel0, vec2(clamp(x, 0.0, 1.0), 0.25)).r; }

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 p = (fragCoord - 0.5 * iResolution.xy) / iResolution.y;
    float bass = iLevel.x, mid = iLevel.y, treb = iLevel.z, energy = iLevel.w;
    float beat = iBeat.x * iBeat.w;
    // gentle sway
    p += 0.06 * vec2(sin(iTime * 0.21), cos(iTime * 0.17));
    float r = length(p) + 1e-3;
    float a = atan(p.y, p.x);
    float z = 0.35 / r;                                  // depth
    float speed = 0.6 + 2.2 * energy + 0.8 * beat;
    float d = z + iTime * speed;

    float ring = fract(d);
    float idx = floor(d);
    float band = fract(idx * 0.137);                     // pseudo-random band per ring
    float s = spec(band * 0.8 + 0.03);
    float line = smoothstep(0.08, 0.0, abs(ring - 0.5) - 0.02 * (1.0 + s * 4.0));

    // segment the rings angularly, segment count follows treble
    float segs = 6.0 + floor(treb * 10.0);
    float seg = smoothstep(0.0, 0.08, abs(fract(a / 6.2831 * segs + idx * 0.25) - 0.5) - 0.1);

    vec3 hue = 0.5 + 0.5 * cos(6.2831 * (band + iTime * 0.03 + vec3(0.0, 0.25, 0.6)));
    float fog = exp(-z * 0.18);
    vec3 col = hue * line * seg * (0.25 + 1.6 * s) * fog;
    // walls
    col += vec3(0.05, 0.04, 0.12) * fog * (0.5 + 0.5 * sin(a * 3.0 + d));
    // center light pulses with bass
    col += vec3(1.0, 0.75, 0.5) * exp(-r * 18.0) * (0.3 + 1.5 * bass);
    col += vec3(0.4, 0.6, 1.0) * exp(-r * 4.0) * mid * 0.25;

    col = 1.0 - exp(-col * 1.5);
    fragColor = vec4(col, 1.0);
}
