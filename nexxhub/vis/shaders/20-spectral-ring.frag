// Spectral ring: mirrored log spectrum around a circle, waveform orbit inside, bass breathes the radius.
// nv:scale=0.5
float spec(float x) { return texture(iChannel0, vec2(clamp(x, 0.0, 1.0), 0.25)).r; }
float wave(float x) { return texture(iChannel0, vec2(clamp(x, 0.0, 1.0), 0.75)).r; }

void mainImage(out vec4 fragColor, in vec2 fragCoord) {
    vec2 p = (fragCoord - 0.5 * iResolution.xy) / iResolution.y;
    float r = length(p);
    float a = atan(p.y, p.x);                 // -pi..pi
    float u = abs(a) / 3.14159265;            // mirrored 0..1 (bass at the top)
    u = 1.0 - u;
    float bass = iLevel.x, mid = iLevel.y, treb = iLevel.z;
    float beat = iBeat.x * iBeat.w;

    // background: slow radial gradient + faint rotating rays
    vec3 col = vec3(0.012, 0.012, 0.03) + vec3(0.04, 0.02, 0.08) * (1.0 - r);
    col += vec3(0.02, 0.03, 0.06) * pow(0.5 + 0.5 * sin(a * 12.0 + iTime * 0.2), 8.0) * (1.0 - r);

    float R = 0.24 + 0.05 * bass + 0.05 * beat;
    // quantise into bars
    float bars = 96.0;
    float bi = floor(u * bars) / bars;
    float s = spec(bi * 0.85 + 0.02);
    float gapm = smoothstep(0.0, 0.18, fract(u * bars)) * smoothstep(1.0, 0.82, fract(u * bars));
    float h = 0.02 + 0.30 * s * s;
    float bar = step(R, r) * step(r, R + h) * gapm;
    vec3 hue = 0.5 + 0.5 * cos(6.2831 * (bi * 0.8 + iTime * 0.02 + vec3(0.0, 0.33, 0.67)));
    col += hue * bar * (0.6 + 0.8 * s);
    // soft glow beyond the bar tips
    col += hue * 0.15 * beat * exp(-abs(r - R) * 20.0);
    col += hue * exp(-max(r - R - h, 0.0) * 30.0) * step(R, r) * s * 0.35 * gapm;

    // inner waveform orbit
    float w = wave(fract(u * 0.5 + 0.25)) - 0.5;
    float rw = R * 0.72 + w * 0.12;
    col += vec3(0.6, 0.85, 1.0) * exp(-abs(r - rw) * 140.0) * (0.35 + 0.8 * mid);

    // core
    col += vec3(0.9, 0.5, 1.0) * exp(-r * (14.0 - 6.0 * bass)) * (0.2 + 0.9 * bass);
    // treble sparkle on the rim
    float sp = fract(sin(dot(floor(fragCoord / 2.0), vec2(12.9898, 78.233)) + floor(iTime * 12.0)) * 43758.5);
    col += step(0.9985 - 0.002 * treb, sp) * smoothstep(R + 0.35, R, r) * treb;

    col = 1.0 - exp(-col * 1.3);
    fragColor = vec4(col, 1.0);
}
