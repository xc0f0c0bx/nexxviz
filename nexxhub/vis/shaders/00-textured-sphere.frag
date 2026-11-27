// Textured Sphere — auto-rotating wireframe spiked sphere, high sensitivity.
// Native GLSL for nexxvis. Raymarched displaced sphere rendered as a
// lat/long wireframe only: no shading fill, no reflection. Bass drives the
// spikes hard; the beat flashes the mesh. The whole sphere (and its grid)
// rotates around Y so the silhouette keeps changing.
// nv:scale=0.25
//
vec3 nvRotY(vec3 v, float a) {
    float c = cos(a), s = sin(a);
    return vec3(c * v.x - s * v.z, v.y, s * v.x + c * v.z);
}

float nvDisp(vec3 n, float t, float bass, float beat) {
    float s1 = sin(n.x * 7.0 + t * 0.60) * sin(n.y * 8.0 - t * 0.45)
             * sin(n.z * 7.5 + t * 0.55);
    float s2 = sin(n.x * 13.0 - t * 0.90) * sin(n.y * 11.0 + t * 0.75)
             * sin(n.z * 12.0 - t * 0.65);
    float v = max(0.0, s1); v = v * v;
    float w = max(0.0, s2); w = w * w;
    return (v * 0.50 + w * 0.15) * (0.55 + 2.20 * bass + 0.60 * beat);
}

float nvMap(vec3 p, float t, float bass, float beat) {
    float r = length(p);
    if (r < 1e-4) return 1.0;
    vec3 n = nvRotY(p / r, -t * 0.35);
    return r - (0.92 + nvDisp(n, t, bass, beat));
}

void mainImage(out vec4 c, in vec2 p) {
    vec2 uv = (p - 0.5 * iResolution.xy) / iResolution.y;
    float t = iTime, bass = iLevel.x, beat = iBeat.x * iBeat.w;
    vec3 ro = vec3(0.0, 0.35, -4.0);
    vec3 rd = normalize(vec3(uv * 1.05, 1.0));

    float tt = 0.0, hit = -1.0;
    for (int i = 0; i < 40; i++) {
        float d = nvMap(ro + rd * tt, t, bass, beat);
        if (d < 0.002) { hit = tt; break; }
        tt += max(d * 0.65, 0.008);
        if (tt > 7.0) break;
    }

    vec3 col = vec3(0.002, 0.004, 0.010);
    if (hit > 0.0) {
        float t0 = max(hit - 0.05, 0.0), t1 = hit;
        for (int j = 0; j < 2; j++) {
            float tm = 0.5 * (t0 + t1);
            if (nvMap(ro + rd * tm, t, bass, beat) > 0.0) t0 = tm;
            else t1 = tm;
        }
        hit = 0.5 * (t0 + t1);
        vec3 pos = ro + rd * hit;
        vec3 rn = nvRotY(normalize(pos), -t * 0.35);

        /* lat/long wireframe, anti-aliased with derivatives */
        float lon = atan(rn.z, rn.x) * 20.0 / 6.2831853;
        float lat = asin(clamp(rn.y, -1.0, 1.0)) * 12.0 / 3.14159265;
        float gl = abs(fract(lon) - 0.5);
        float gt = abs(fract(lat) - 0.5);
        float wl = fwidth(lon) * 1.25 + 0.006;
        float wt = fwidth(lat) * 1.25 + 0.006;
        float line = max(smoothstep(wl, 0.0, gl), smoothstep(wt, 0.0, gt));

        float edge = exp(-max(hit - 2.0, 0.0) * 0.08);
        float d0 = nvDisp(rn, t, bass, beat);
        vec3 mesh = mix(vec3(0.15, 0.85, 0.25), vec3(0.95, 0.95, 0.20),
                        clamp(d0 * 1.5, 0.0, 1.0));
        col += mesh * line * edge * (0.70 + 1.40 * beat);
        col += mesh * 0.045 * exp(-abs(length(pos) - 1.2) * 6.0) * edge;
    }

    col *= 1.0 - 0.45 * smoothstep(0.70, 1.30, length(uv));
    c = vec4(col, 1.0);
}
