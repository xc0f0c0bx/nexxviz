// Crop Orbital — a three-dimensional orbital reading of the crop genesis.
// The formation leaves the plane: the baked crown rings become inclined
// orbital tracks and the satellites travel inclined orbits with depth-
// scaled size and brightness.  Kept as a separate visualizer; crop genesis
// is unchanged.
// nv:scale=0.42
//
vec3 hueShift(vec3 c, float a) {
    const vec3 k = vec3(0.57735027);
    float ca = cos(a);
    return c * ca + cross(k, c) * sin(a) + k * dot(k, c) * (1.0 - ca);
}

float nvHash(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

float nvAA = 0.0016;
float nvLine(float d, float w) {
    return 1.0 - smoothstep(w, w + nvAA, abs(d));
}
float sdRing(vec2 p, vec2 c, float r) {
    vec2 d = p - c;
    return (dot(d, d) - r * r) * (0.5 / max(r, 1e-4));
}

void mainImage(out vec4 c, in vec2 p) {
    vec2 uv = (p - 0.5 * iResolution.xy) / iResolution.y;
    float t = iTime, bass = iLevel.x, mid = iLevel.y, treb = iLevel.z;
    float beat = iBeat.x * iBeat.w;
    vec3 gA = hueShift(iCoverA, iHue);
    vec3 gB = hueShift(iCoverB, iHue);

    float gZoom = clamp(iGenomeB.z, 0.70, 1.30);
    nvAA = 0.0027 / gZoom;
    float nd = iStory.x >= 0.5 ? clamp(iStory.x, 1.0, 97.0) : 7.0;

    /* camera: a slow screen turn and a gentle tilt that squashes y */
    float camA = t * 0.03;
    vec2 q = mat2(cos(camA), -sin(camA), sin(camA), cos(camA)) * (uv / (0.55 * gZoom));
    q.y /= 0.94 + 0.05 * sin(t * 0.06);
    float r = length(q);

    /* deep space: the straw field, dark and cool, slowly turning */
    float bAng = -t * 0.02;
    vec2 fq = mat2(cos(bAng), -sin(bAng), sin(bAng), cos(bAng)) * q;
    vec3 col = texture(iChannel1, fq * 0.2083333 + 0.5).rgb * vec3(0.08, 0.09, 0.13);
    col += vec3(0.010, 0.014, 0.028) * (1.0 - smoothstep(0.15, 1.10, r));
    col += vec3(0.035, 0.025, 0.080) * exp(-r * 1.6);
    vec2 sp = fq * 10.0;
    vec2 cell = floor(sp);
    vec2 sf = fract(sp) - 0.5;
    float sh = nvHash(cell);
    float star = step(0.982, sh) * smoothstep(0.10, 0.0, length(sf))
               * (0.25 + 0.75 * sh);
    col += vec3(0.80, 0.90, 1.00) * star * 0.8;

    /* nucleus: the baked nine-point circuit, small, plus a hot core */
    float Rn = (0.13 + 0.02 * bass) * gZoom;
    vec2 ln = mat2(cos(-t * 0.18), -sin(-t * 0.18),
                   sin(-t * 0.18), cos(-t * 0.18)) * q / Rn;
    vec4 tv = texture(iChannel4, ln * 0.4166667 + 0.5);
    col += vec3(1.0, 0.72, 0.25) * tv.r * (0.45 + 0.35 * beat + 0.20 * mid);
    col += vec3(0.25, 0.80, 1.0) * tv.g * (0.40 + 0.30 * beat);
    col += vec3(1.0, 0.95, 0.78) * tv.b * (0.35 + 0.25 * mid);
    col += vec3(1.0, 0.82, 0.55) * exp(-r * 16.0) * (0.35 + 0.45 * beat);

    /* three inclined orbital tracks: the baked crown rings, squashed by
       their inclination and turned in the screen plane */
    for (int m = 0; m < 3; m++) {
        float fm = float(m);
        float incl = 0.38 + 0.32 * fm;
        float ci = cos(incl);
        float Rr = (0.52 + 0.15 * fm + 0.05 * bass) * gZoom;
        float rot = (mod(fm, 2.0) < 0.5 ? 1.0 : -1.0) * t * (0.045 + 0.015 * fm) + 0.6 * fm;
        vec2 sq = vec2(q.x, q.y / ci);
        float re = length(sq);
        if (abs(re - Rr * 0.94) < Rr * 0.12) {
            vec2 lc = mat2(cos(rot), -sin(rot), sin(rot), cos(rot)) * sq / Rr;
            float ctex;
            if (m == 0) ctex = texture(iChannel6, lc * 0.4166667 + 0.5).r;
            else if (m == 1) ctex = texture(iChannel7, lc * 0.4166667 + 0.5).r;
            else ctex = texture(iChannel8, lc * 0.4166667 + 0.5).r;
            col += vec3(0.60, 0.82, 1.0) * ctex * (0.75 + 0.25 * beat);
        }
        col += vec3(0.30, 0.55, 0.95) * nvLine(re - Rr, 0.0016) * 0.18;
    }

    /* the rose: a central ring seen at an angle */
    float Rb = (0.30 + 0.03 * bass) * gZoom;
    vec2 rq = vec2(q.x, q.y / 0.80);
    float re2 = length(rq);
    if (abs(re2 - Rb * 0.94) < Rb * 0.14) {
        vec2 lr = mat2(cos(-t * 0.07), -sin(-t * 0.07),
                       sin(-t * 0.07), cos(-t * 0.07)) * rq / Rb;
        col += vec3(1.0, 0.55, 0.85)
             * texture(iChannel5, lr * 0.4166667 + 0.5).r * 0.55;
    }

    /* satellites on inclined orbits: position, depth, size, brightness */
    float count = 3.0 + clamp(floor(nd / 4.0), 0.0, 5.0);
    for (int j = 0; j < 8; j++) {
        float fj = float(j);
        if (fj >= count) continue;
        float incl = 0.22 + 0.55 * fract(fj * 0.6180339 + 0.17);
        float ci = cos(incl), si = sin(incl);
        float spd = 0.10 + 0.05 * fract(fj * 0.7548776 + 0.29);
        float dir = mod(fj, 2.0) < 0.5 ? 1.0 : -1.0;
        float phi = dir * t * spd * (1.0 + 0.15 * beat) + 6.2831853 * fj / count;
        float Rorb = (0.52 + 0.20 * fract(fj * 0.381966 + 0.11) + 0.05 * bass) * gZoom;
        vec2 pos = Rorb * vec2(cos(phi), sin(phi) * ci);
        float depth = sin(phi) * si;                 /* -1 behind .. +1 front */
        float scale = 1.0 / (1.0 - 0.30 * depth);
        float rr = (0.020 + 0.012 * fract(fj * 0.6180339 + 0.5)) * scale;
        /* the body's own inclined orbit, very faint */
        float oe = length(vec2(q.x, q.y / ci)) - Rorb;
        if (abs(oe) < 0.008)
            col += vec3(0.25, 0.45, 0.90) * nvLine(oe, 0.0010) * 0.06;
        vec2 d = q - pos;
        float dist = length(d);
        if (abs(dist - rr) < rr * 0.6 + nvAA * 2.0) {
            float body = nvLine(sdRing(q, pos, rr), 0.0022);
            vec3 bc = mix(gA, gB, fract(fj * 0.6180339 + 0.2));
            float lum = 0.60 + 0.40 * (0.5 + 0.5 * depth);
            col += (bc * 0.85 + 0.15) * body * lum * (0.75 + 0.25 * beat);
            col += bc * exp(-dist * 60.0 / scale) * 0.06 * lum;
        }
        /* a faint trail behind the body, squashed into the orbit plane */
        float tr = length(vec2(q.x - pos.x, (q.y - pos.y) / ci));
        if (tr < rr * 4.0) {
            col += vec3(0.40, 0.60, 1.0) * exp(-tr * 22.0 / scale) * 0.05;
        }
    }

    /* tone */
    float lum = dot(col, vec3(0.299, 0.587, 0.114));
    col = mix(vec3(lum), col, 1.25);
    col = max(col, vec3(0.0));
    col *= 1.0 + 0.10 * beat;
    col *= 1.0 - 0.35 * smoothstep(0.75, 1.35, length(uv));
    c = vec4(col, 1.0);
}
