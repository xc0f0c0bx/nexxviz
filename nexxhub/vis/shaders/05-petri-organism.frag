// Petri Organism — a black ink bloom in a lit petri dish, after the
// "Birth of the Universe" practical: luminous porcelain dish, smoky ink
// organism with tender cilia, dust specks, dark field. The organism is a
// raymarched displaced sphere shaded as wet ink; a low-frequency asymmetric
// warp is applied to the direction before the wave field, so the two halves
// are NOT mirror images (the old product-of-sines was antisymmetric in each
// axis and produced a bilateral mirror).
// nv:scale=0.25
//
vec3 nvRotY(vec3 v, float a) {
    float c = cos(a), s = sin(a);
    return vec3(c * v.x - s * v.z, v.y, s * v.x + c * v.z);
}

float nvHash(vec3 p) {
    return fract(sin(dot(p, vec3(12.9898, 78.233, 37.719))) * 43758.5453);
}

float nvNoise(vec3 p) {
    vec3 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = mix(nvHash(i), nvHash(i + vec3(1,0,0)), f.x);
    float b = mix(nvHash(i + vec3(0,1,0)), nvHash(i + vec3(1,1,0)), f.x);
    float c = mix(nvHash(i + vec3(0,0,1)), nvHash(i + vec3(1,0,1)), f.x);
    float d = mix(nvHash(i + vec3(0,1,1)), nvHash(i + vec3(1,1,1)), f.x);
    return mix(mix(a, b, f.y), mix(c, d, f.y), f.z);
}

float nvDisp(vec3 n, float t, float bass, float beat) {
    /* asymmetric warp: the two hemispheres become different blooms */
    vec3 w = n + 0.16 * vec3(sin(n.y * 3.1 + t * 0.40),
                             sin(n.z * 2.7 - t * 0.30),
                             sin(n.x * 3.3 + t * 0.50));
    w = normalize(w);
    float s1 = sin(w.x * 9.0 + w.y * 4.0 + t * 0.35)
             * sin(w.y * 11.0 - w.z * 3.0 - t * 0.25)
             * sin(w.z * 10.0 + t * 0.40);
    float s2 = sin(w.x * 23.0 - t * 0.80)
             * sin(w.y * 27.0 + t * 0.60)
             * sin(w.z * 31.0 - t * 0.70);
    float v = max(0.0, s1); v = v * v;
    float u = max(0.0, s2); u = u * u * u;
    return (0.17 * v + 0.050 * u) * (0.60 + 1.60 * bass + 0.50 * beat);
}

float nvMap(vec3 p, float t, float bass, float beat) {
    float r = length(p);
    if (r < 1e-4) return 1.0;
    vec3 n = nvRotY(p / r, -t * 0.22);
    return r - (0.72 + nvDisp(n, t, bass, beat));
}

vec3 nvOrganism(vec3 ro, vec3 rd, float t, float bass, float beat,
                float gain, float soft, out float cov, out float mdOut) {
    float tt = 0.0, hit = -1.0, md = 1e9;
    for (int i = 0; i < 48; i++) {
        float d = nvMap(ro + rd * tt, t, bass, beat) * (1.0 + soft);
        md = min(md, d);
        if (d < 0.002) { hit = tt; break; }
        tt += max(d * 0.60, 0.008);
        if (tt > 6.0) break;
    }
    if (hit < 0.0) { cov = 0.0; mdOut = md; return vec3(0.0); }
    cov = 1.0; mdOut = 0.0;

    float t0 = max(hit - 0.05, 0.0), t1 = hit;
    for (int j = 0; j < 2; j++) {
        float tm = 0.5 * (t0 + t1);
        if (nvMap(ro + rd * tm, t, bass, beat) > 0.0) t0 = tm;
        else t1 = tm;
    }
    hit = 0.5 * (t0 + t1);

    vec3 p = ro + rd * hit;
    vec3 n = normalize(p);
    vec3 rn = nvRotY(n, -t * 0.22);
    float d0 = nvDisp(rn, t, bass, beat);

    vec3 t1v = normalize(cross(n, vec3(0.0, 1.0, 0.0)) + vec3(1e-4));
    vec3 t2v = cross(n, t1v);
    float e = 0.03;
    float m1 = nvDisp(nvRotY(normalize(n + t1v * e), -t * 0.22), t, bass, beat) - d0;
    float m2 = nvDisp(nvRotY(normalize(n + t2v * e), -t * 0.22), t, bass, beat) - d0;
    vec3 nrm = normalize(n - (t1v * m1 + t2v * m2) * 4.0);

    float speck = nvNoise(rn * 6.0 + vec3(0.0, 0.0, t * 0.10));
    float vein  = smoothstep(0.50, 0.80, nvNoise(rn * 9.0 + vec3(t * 0.05)));
    vec3 ink  = vec3(0.030, 0.034, 0.042);
    vec3 smoke = vec3(0.42, 0.44, 0.47);
    vec3 body = mix(ink, smoke, clamp(0.12 + 0.50 * d0 + 0.30 * speck, 0.0, 0.75));

    vec3 L = normalize(vec3(-0.45, 0.80, -0.40));
    float diff = max(dot(nrm, L), 0.0);
    float fres = pow(1.0 - max(dot(n, -rd), 0.0), 2.0);
    float spec = pow(max(dot(reflect(-L, nrm), -rd), 0.0), 30.0);
    float back = pow(max(dot(-nrm, L), 0.0), 2.0);

    vec3 col = body * (0.45 + 1.00 * diff);
    col += vec3(0.72, 0.75, 0.78) * back * 0.22;    /* translucent ink */
    col += vec3(0.85, 0.87, 0.90) * fres * 0.30;    /* wet meniscus edge */
    col += vec3(1.0) * spec * 0.35;                 /* specular */
    col -= vec3(0.06, 0.06, 0.07) * vein;           /* dark filaments */
    return col * gain * exp(-max(hit - 1.9, 0.0) * 0.12);
}

vec3 nvDish(vec2 uv, float t, out float mask, out float rr) {
    vec2 d = (uv - vec2(0.06, 0.02)) / vec2(0.80, 0.53);
    rr = length(d);
    mask = smoothstep(1.02, 0.965, rr);

    /* porcelain medium: bright core falling off toward the rim */
    vec3 med = mix(vec3(0.52, 0.54, 0.55), vec3(0.97, 0.97, 0.96),
                   smoothstep(1.05, 0.10, rr));
    /* mottling + meniscus rings */
    med *= 0.93 + 0.07 * nvNoise(vec3(d * 3.0, t * 0.03));
    med += vec3(0.06) * (0.5 + 0.5 * sin(rr * 21.0 - t * 0.15))
         * smoothstep(0.55, 1.0, rr);
    /* dark ink clouds already suspended in the medium */
    float w1 = nvNoise(vec3(d * 1.7 + 3.0, t * 0.030));
    float w2 = nvNoise(vec3(d * 4.2 + 11.0, t * 0.045));
    med -= vec3(0.42, 0.43, 0.44) * smoothstep(0.40, 0.92, w1)
         * smoothstep(0.15, 0.95, rr);
    med -= vec3(0.15, 0.16, 0.16) * smoothstep(0.52, 0.88, w2) * 0.7;
    /* stretched filaments drifting in the medium */
    med -= vec3(0.10) * smoothstep(0.55, 0.82,
         nvNoise(vec3(d.x * 5.0, d.y * 13.0, t * 0.02))) * smoothstep(0.25, 0.95, rr);
    /* a few dark specks on the surface */
    vec2 sc = floor(uv * 55.0);
    vec2 so = fract(uv * 55.0) - 0.5;
    float sh = nvHash(vec3(sc, 2.0));
    med -= vec3(0.45) * smoothstep(0.16, 0.05, length(so)) * step(0.975, sh);
    /* bright rim and inner meniscus */
    med += vec3(0.55) * exp(-abs(rr - 1.0) * 70.0);
    med += vec3(0.28) * exp(-abs(rr - 0.93) * 130.0);
    return med * mask;
}

void mainImage(out vec4 c, in vec2 p) {
    vec2 uv = (p - 0.5 * iResolution.xy) / iResolution.y;
    float t = iTime, bass = iLevel.x, beat = iBeat.x * iBeat.w;
    vec3 ro = vec3(0.0, 0.32, -3.6);
    vec3 rd = normalize(vec3(uv * 1.05, 1.0));

    vec3 col = vec3(0.004, 0.005, 0.007);
    float dishMask, rr;
    col += nvDish(uv, t, dishMask, rr);

    /* dust drifting in the dark around the dish */
    vec2 dc = floor(uv * 70.0);
    vec2 dof = fract(uv * 70.0) - 0.5;
    float dh = nvHash(vec3(dc, 1.0));
    float dust = smoothstep(0.10, 0.01, length(dof)) * step(0.986, dh);
    col += vec3(0.55, 0.56, 0.58) * dust * (1.0 - dishMask);

    float cov, md;
    vec3 org = nvOrganism(ro, rd, t, bass, beat, 1.0, 0.0, cov, md);
    col = mix(col, org, cov);
    /* ink bleeding into the medium where rays graze the bloom */
    col -= vec3(0.16, 0.17, 0.18) * exp(-md * 16.0) * dishMask;

    col *= 1.0 - 0.45 * smoothstep(0.70, 1.30, length(uv));
    c = vec4(col, 1.0);
}
