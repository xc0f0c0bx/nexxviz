// Mesh Grid — a floating wireframe heightfield in a black void.
// Raymarched terrain; grid lines are drawn on the hit point. Bass raises the
// waves, the beat flashes the mesh, treble adds sparkle. Silent = calm drift.
// nv:scale=0.30
//
float nvSpec(float x) {
    return texture(iChannel0, vec2(clamp(x, 0.0, 1.0), 0.25)).r;
}

float nvH(vec2 p, float t, float bass) {
    float h = 0.54 * sin(p.x * 0.82 + t * 0.27);
    h += 0.38 * sin(p.y * 0.63 - t * 0.19);
    h += 0.25 * sin((p.x + p.y) * 1.13 + t * 0.41);
    h += (0.12 + 0.65 * bass) * sin(p.y * 0.88 + t * 0.55);
    h += 0.09 * sin(p.x * 2.05 - p.y * 1.62 + t * 0.70);
    return h;
}

vec3 nvTerrain(vec2 uv, float t, float bass, float treb, float beat, float gain,
               vec3 tint, float yOff) {
    vec3 ro = vec3(0.0, 1.05 + yOff, -3.05 + t * 0.050);
    vec3 rd = normalize(vec3(uv.x * 0.95, uv.y * 0.72 - 0.08, 1.0));
    float tt = 0.0, hit = -1.0;
    for (int i = 0; i < 56; i++) {
        vec3 p = ro + rd * tt;
        float d = p.y - nvH(p.xz, t, bass) - yOff;
        if (d < 0.002) { hit = tt; break; }
        tt += clamp(d * 0.62, 0.02, 0.55);
        if (tt > 13.0) break;
    }
    if (hit < 0.0) return vec3(0.0);
    /* bisection: smooth the hit point so the grid lines do not stair-step */
    float t0 = max(hit - 0.35, 0.0), t1 = hit;
    for (int j = 0; j < 5; j++) {
        float tm = 0.5 * (t0 + t1);
        vec3 pm = ro + rd * tm;
        if (pm.y - nvH(pm.xz, t, bass) - yOff > 0.0) t0 = tm;
        else t1 = tm;
    }
    hit = 0.5 * (t0 + t1);

    vec3 p = ro + rd * hit;
    vec2 g = p.xz * 3.60;
    vec2 f = abs(fract(g) - 0.5);
    vec2 w = fwidth(g) * 1.10 + 0.006;
    float line = max(1.0 - smoothstep(0.0, w.x, f.x),
                     1.0 - smoothstep(0.0, w.y, f.y));

    float fade = exp(-max(hit - 1.2, 0.0) * 0.20);
    float edge = exp(-length(p.xz) * 0.22);       /* floating island edge */
    float shimmer = 0.80 + 0.20 * sin(g.x * 0.5 - t * 1.2 + g.y * 0.3)
                  + 0.25 * treb * nvSpec(0.10 + 0.20 * abs(uv.x));
    float amp = 0.75 + 1.25 * beat + 0.35 * nvSpec(0.15 + 0.2 * abs(uv.x));
    vec3 col = tint * line * fade * edge * shimmer * amp * gain;
    col += tint * 0.06 * fade * edge * (0.5 + bass);
    return col;
}

void mainImage(out vec4 c, in vec2 p) {
    vec2 uv = (p - 0.5 * iResolution.xy) / iResolution.y;
    float t = iTime;
    float bass = iLevel.x, treb = iLevel.z;
    float beat = iBeat.x * iBeat.w;

    vec3 col = vec3(0.002, 0.002, 0.006);
    /* dim reflection below, main surface, and a faint upper ghost */
    col += nvTerrain(uv, t * 1.10, bass, treb, beat, 0.34, vec3(0.36, 0.34, 0.62), -0.50);
    col += nvTerrain(uv, t,        bass, treb, beat, 1.15, vec3(0.80, 0.78, 1.00),  0.00);
    col += nvTerrain(uv, t * 0.82, bass, treb, beat, 0.38, vec3(0.44, 0.42, 0.74),  0.50);

    col += vec3(0.10, 0.08, 0.20) * exp(-length(uv * vec2(1.1, 1.7)) * 2.2)
         * (0.25 + 0.85 * beat);
    col *= 1.0 - 0.50 * smoothstep(0.5, 1.3, length(uv * vec2(1.0, 0.9)));
    c = vec4(col, 1.0);
}
