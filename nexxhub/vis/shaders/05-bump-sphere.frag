// Bump Sphere — dense audio-driven spiked sphere, auto-rotating.
// Mirrors the vizz.fm Textured Sphere (variant 9) bump look: high-frequency
// radial displacement (noise scale ~31), long needles under audio, solid
// shaded surface with a soft floor reflection. Green body, yellow tips.
// nv:scale=0.25
//
vec3 nvRotY(vec3 v, float a) {
    float c = cos(a), s = sin(a);
    return vec3(c * v.x - s * v.z, v.y, s * v.x + c * v.z);
}

float nvDisp(vec3 n, float t, float bass, float beat) {
    float s1 = sin(n.x * 23.0 + t * 0.70) * sin(n.y * 27.0 - t * 0.50)
             * sin(n.z * 21.0 + t * 0.60);
    float s2 = sin(n.x * 37.0 - t * 1.10) * sin(n.y * 31.0 + t * 0.90)
             * sin(n.z * 41.0 - t * 0.80);
    float v = max(0.0, s1); v = v * v;
    float w = max(0.0, s2); w = w * w * w;
    return (v * 0.30 + w * 0.14) * (0.30 + 1.80 * bass + 0.60 * beat);
}

float nvMap(vec3 p, float t, float bass, float beat) {
    float r = length(p);
    if (r < 1e-4) return 1.0;
    vec3 n = nvRotY(p / r, -t * 0.30);
    return r - (0.85 + nvDisp(n, t, bass, beat));
}

vec3 nvShade(vec3 ro, vec3 rd, float t, float bass, float beat,
             float gain, float soften) {
    float tt = 0.0, hit = -1.0;
    for (int i = 0; i < 48; i++) {
        float d = nvMap(ro + rd * tt, t, bass, beat) * (1.0 + soften);
        if (d < 0.002) { hit = tt; break; }
        tt += max(d * 0.60, 0.008);
        if (tt > 7.0) break;
    }
    if (hit < 0.0) return vec3(0.0);
    float t0 = max(hit - 0.06, 0.0), t1 = hit;
    for (int j = 0; j < 2; j++) {
        float tm = 0.5 * (t0 + t1);
        if (nvMap(ro + rd * tm, t, bass, beat) > 0.0) t0 = tm;
        else t1 = tm;
    }
    hit = 0.5 * (t0 + t1);
    vec3 p = ro + rd * hit;
    vec3 n = normalize(p);
    vec3 rn = nvRotY(n, -t * 0.30);
    float d0 = nvDisp(rn, t, bass, beat);

    vec3 t1v = normalize(cross(n, vec3(0.0, 1.0, 0.0)) + vec3(1e-4));
    vec3 t2v = cross(n, t1v);
    float e = 0.03;
    float m1 = nvDisp(nvRotY(normalize(n + t1v * e), -t * 0.30), t, bass, beat) - d0;
    float m2 = nvDisp(nvRotY(normalize(n + t2v * e), -t * 0.30), t, bass, beat) - d0;
    vec3 nrm = normalize(n - (t1v * m1 + t2v * m2) * 4.0);

    vec3 L = normalize(vec3(0.55, 0.80, -0.55));
    float diff = max(dot(nrm, L), 0.0);
    float spec = pow(max(dot(reflect(-L, nrm), -rd), 0.0), 26.0);
    float rim = pow(1.0 - max(dot(n, -rd), 0.0), 2.2);
    vec3 body = mix(vec3(0.10, 0.80, 0.25), vec3(0.95, 0.95, 0.20),
                    clamp(d0 * 2.0, 0.0, 1.0));
    vec3 col = body * (0.25 + 1.10 * diff);
    col += vec3(1.0, 0.95, 0.6) * spec * 0.9;
    col += vec3(1.0, 0.25, 0.45) * rim * (0.30 + 0.35 * beat);
    return col * gain * exp(-max(hit - 2.2, 0.0) * 0.07);
}

void mainImage(out vec4 c, in vec2 p) {
    vec2 uv = (p - 0.5 * iResolution.xy) / iResolution.y;
    float t = iTime, bass = iLevel.x, beat = iBeat.x * iBeat.w;
    vec3 ro = vec3(0.0, 0.35, -3.8);
    vec3 rd = normalize(vec3(uv * 1.05, 1.0));

    vec3 col = mix(vec3(0.005, 0.008, 0.02), vec3(0.02, 0.035, 0.09),
                   smoothstep(-0.6, 0.7, uv.y));
    col += nvShade(ro, rd, t, bass, beat, 1.0, 0.0);

    /* soft floor reflection */
    if (uv.y < 0.02) {
        vec3 rom = vec3(ro.x, -ro.y - 2.4, ro.z);
        vec3 rdm = normalize(vec3(rd.x, -rd.y, rd.z));
        col += nvShade(rom, rdm, t * 1.05, bass * 0.8, beat, 0.28, 0.45)
             * smoothstep(0.02, -0.45, uv.y);
    }

    col *= 1.0 - 0.40 * smoothstep(0.70, 1.30, length(uv));
    c = vec4(col, 1.0);
}
