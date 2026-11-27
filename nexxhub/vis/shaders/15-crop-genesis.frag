// Crop Genesis — a developing crop-circle formation.
// Not a UI: a generative grammar grows the formation from the templates in
// images_template (Mammendorf seed-of-life cluster, Kornkreis triskele and
// golden-section constructions).  Elements are drawn in sequence, so the
// field is "being formed".  The genome selects the rules; the novelty term
// in evolve.py keeps pushing the rules into forms it has not tried before.
// nv:scale=0.42
//
vec3 hueShift(vec3 c, float a) {
    const vec3 k = vec3(0.57735027);
    float ca = cos(a);
    return c * ca + cross(k, c) * sin(a) + k * dot(k, c) * (1.0 - ca);
}
vec3 gA, gB;

/* sin-free hash: avoids four SFU sine calls per noise sample */
float nvHash(vec2 p) {
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
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

/* first-order ring distance (|p-c|^2 - r^2) / 2r: exact at the stroke
   centre and within w^2/(2r) of exact at its edge, so r >> w makes the
   sqrt unnecessary for the ~37 circle strokes drawn per pixel */
float sdRing(vec2 p, vec2 c, float r) {
    vec2 d = p - c;
    return (dot(d, d) - r * r) * (0.5 / max(r, 1e-4));
}

/* squared segment distance: a stroke test against squared thresholds is
   equivalent to the linear test, without the sqrt */
float sdSegSq(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a, ba = b - a;
    float h = clamp(dot(pa, ba) / max(dot(ba, ba), 1e-6), 0.0, 1.0);
    vec2 d = pa - ba * h;
    return dot(d, d);
}

float nvAA = 0.0016;
float nvLine(float d, float w) {
    return 1.0 - smoothstep(w, w + nvAA, abs(d));
}
float nvLineSq(float d2, float w) {
    float e = w + nvAA;
    return 1.0 - smoothstep(w * w, e * e, d2);
}
/* axis-aligned gate: a stroke can only paint inside its segment's box */
bool nvBox(vec2 p, vec2 a, vec2 b, float m) {
    vec2 mid = 0.5 * (a + b);
    vec2 hw = 0.5 * abs(a - b) + m;
    return abs(p.x - mid.x) <= hw.x && abs(p.y - mid.y) <= hw.y;
}

/* Vortex-math node: 1..9 on a nine-point circle, 9 at the top */
vec2 nvVortexNode(float i, float Rv, float vr) {
    float ang = 6.2831853 * i / 9.0 + vr + 1.5707963;
    return Rv * vec2(cos(ang), sin(ang));
}

/* Gnostic seal node: seven seals on a heptagram */
vec2 nvSealNode(float k, float Rs, float sr) {
    float ang = 6.2831853 * k / 7.0 + sr + 1.5707963;
    return Rs * vec2(cos(ang), sin(ang));
}

/* arc of a circle: circle line gated by a draw-in sweep from -pi */

void mainImage(out vec4 c, in vec2 p) {
    vec2 uv = (p - 0.5 * iResolution.xy) / iResolution.y;
    float t = iTime, bass = iLevel.x, mid = iLevel.y, treb = iLevel.z;
    float beat = iBeat.x * iBeat.w;
    gA = hueShift(iCoverA, iHue);
    gB = hueShift(iCoverB, iHue);

    float gBands = clamp(iGenomeA.y, 3.0, 10.0);
    float gDens  = clamp(iGenomeA.x / 120.0, 0.4, 1.8);
    float gZoom  = clamp(iGenomeB.z, 0.70, 1.30);
    /* one render pixel of AA at the 0.42 scale is ~0.0027 q units at
       gZoom 1, so the band must follow the zoom to stay a full pixel */
    nvAA = 0.0027 / gZoom;
    float gBend  = clamp(iGenomeB.w, 0.0, 0.40);
    float gCol   = clamp(iGenomeB.y, 0.0, 1.0);
    float gInt   = clamp(iGenomeB.x, 0.70, 1.60);

    /* growth: a 75 s formation cycle. Bass accelerates the drawing, the
       beat nudges it, and the cycle edges fade so each new formation starts
       from the field instead of popping. */
    const float CYCLE = 75.0;
    float ct = mod(t, CYCLE);
    float grow = clamp(0.42 + 0.58 * (1.0 - exp(-ct * (0.110 + 0.050 * bass)))
                       + 0.06 * (iEntropy.w - 0.5) + 0.03 * beat, 0.0, 1.0);
    float vis = smoothstep(0.0, 1.5, ct) * smoothstep(CYCLE, CYCLE - 2.0, ct);
    /* n-dimensional steps: every 10 s the formation breaks at the boundary,
       reassembles, and its projection gains a dimension.  The story owns
       the ladder (1..13, or the primes to 97); the timer fallback runs its
       own 130 s ladder to 13. */
    const float STEP = 10.0;
    float autoT = mod(t, STEP * 13.0);
    float stepT = mod(autoT, STEP);
    float autoNd = clamp(1.0 + floor(autoT / STEP)
                         + smoothstep(6.0, 9.0, stepT), 1.0, 13.0);
    /* the story service owns the dimension arc; fall back to the timer
       when it is not running (iStory.x = 0) */
    float nd = iStory.x >= 0.5 ? clamp(iStory.x, 1.0, 97.0) : autoNd;
    /* the break/reassembly is disabled: chapters change by gliding the
       dimension instead, so the field no longer folds at the 9 o'clock edge */
    float brk = 0.0;

    vec2 q = mat2(cos(t * 0.008), -sin(t * 0.008),
                  sin(t * 0.008), cos(t * 0.008)) * (uv / (0.62 * gZoom));
    q.x += 0.10 * gBend * sin(q.y * 1.7 + t * 0.03);
    q = mat2(cos(brk * 0.45), -sin(brk * 0.45),
             sin(brk * 0.45), cos(brk * 0.45)) * q;

    /* SO(n) group element as a per-frame uniform: (cos a4, sin a4, sx, sy).
       The shader only applies the linear 2x2 shadow, so there is no
       per-pixel trig and no possible warp. */
    q = mat2(iSO.x * iSO.z, iSO.y * iSO.z,
             -iSO.y * iSO.w, iSO.x * iSO.w) * q;
    /* continuous curl-like flow */
    q += 0.030 * vec2(sin(q.y * 2.6 + t * 0.60),
                      cos(q.x * 2.9 - t * 0.55));
    float r = length(q), th = atan(q.y, q.x);

    /* straw backdrop: baked into iChannel1 at startup; the clockwise
       rotation stays live, the noise's very slow drift is frozen */
    float bAng = -t * 0.06;
    vec2 fq = mat2(cos(bAng), -sin(bAng), sin(bAng), cos(bAng)) * q;
    vec3 field = texture(iChannel1, fq * 0.2083333 + 0.5).rgb;

    float ns = gBands + 3.0 * treb;
    float n = ns < 6.0 ? 3.0 : (ns < 9.0 ? 5.0 : 8.0);
    n = beat > 0.85 ? 8.0 : n;
    float R  = 0.52 + 0.09 * bass + 0.02 * sin(t * 0.02);
    float rs = 0.080 + 0.040 * mid;
    float rv = 0.095 + 0.040 * (1.0 - bass);
    float satRot = -t * 0.09 + 0.10 * beat;

    /* flattened formation area */
    float flatArea = 1.0 - smoothstep(R + rs, R + rs + 0.012, r);
    float flatMask = flatArea * smoothstep(rv * 0.92, rv, r) * vis
                   * (1.0 - 0.85 * brk);
    vec3 col = field;
    if (flatMask > 0.002) {
        /* the swirl is baked in C (iChannel9: sin, cos of the pattern);
           only its time phase rotates here */
        vec2 sw = texture(iChannel9, q * 0.5 + 0.5).rg;
        float swc = cos(t * 0.18), sws = sin(t * 0.18);
        float swirl = 0.5 + 0.5 * ((sw.r * 2.0 - 1.0) * swc
                                 - (sw.g * 2.0 - 1.0) * sws);
        vec3 flatc = mix(vec3(0.10, 0.08, 0.03),
                         vec3(0.20, 0.16, 0.06), swirl);
        col = mix(field, flatc, flatMask * 0.92);
    }

    float line = 0.0, spiral = 0.0, tick = 0.0, seeds = 0.0;
    float vortex = 0.0, axis = 0.0, vnodes = 0.0;
    float seals = 0.0, hept = 0.0, pent = 0.0, star = 0.0, crown = 0.0;
    float vv = smoothstep(2.2, 3.2, nd);
    float sealVis = smoothstep(1.5, 2.5, nd);
    float pentVis = smoothstep(4.5, 5.0, nd);
    float starVis = smoothstep(7.2, 8.0, nd);
    float crownVis = smoothstep(3.5, 4.0, nd);
    /* the whole vector field fits inside this disk; pixels outside it skip
       every distance-field evaluation.  The break pushes the satellites
       outward, so the bound grows with brk. */
    float rBound = 0.90 + 0.50 * brk;
    if (r < rBound) {

    /* 1. the first circle, then Fibonacci rings, fading in as they grow;
          during the break the rings expand outward */
    float rFirst = rv * (1.0 + 0.55 * brk);
    if (abs(r - rFirst) < 0.02)
        line = max(line, nvLine(sdRing(q, vec2(0.0), rFirst), 0.0045)
                         * smoothstep(0.02, 0.16, grow));
    int rings = 2 + int(floor(clamp(gDens * 1.8, 0.0, 2.9)));
    for (int k = 0; k < 4; k++) {
        if (k < rings) {
            float fk = float(k);
            /* Fibonacci 2..5 as fractions of 8: 1, 2, 3, 5 */
            float ff = fk < 0.5 ? 0.125
                     : (fk < 1.5 ? 0.250 : (fk < 2.5 ? 0.375 : 0.625));
            float thr = 0.10 + 0.10 * fk;
            float rk = (rv + (R - rv) * ff) * (1.0 + 0.55 * brk);
            if (abs(r - rk) < 0.02)
                line = max(line, nvLine(sdRing(q, vec2(0.0), rk), 0.0040)
                                 * smoothstep(thr, thr + 0.12, grow));
        }
    }

    /* 2. satellite circles bud at golden/Fibonacci angles; they fly out.
       The annulus gate skips the eight circles for most pixels. */
    float satR = R * (1.0 + 0.85 * brk);
    if (abs(r - satR) < 0.16) {
        for (int i = 0; i < 8; i++) {
            if (float(i) < n) {
                float fi = float(i);
                float ang = satRot + 6.2831853 * fi / n;
                vec2 cen = satR * vec2(cos(ang), sin(ang));
                float rr = rs * (0.78 + 0.44 * fract(fi * 0.7548776 + 0.31))
                         * (1.0 + 0.15 * brk);
                float thr = 0.32 + 0.03 * fi;
                line = max(line, nvLine(sdRing(q, cen, rr), 0.0040)
                                 * smoothstep(thr, thr + 0.12, grow));
            }
        }
    }

    /* 3. triskele: three log spirals, from the Kornkreis template */
    float spin = smoothstep(0.50, 0.72, grow);
    if (r < 0.87) {
        for (int i = 0; i < 3; i++) {
            float arm = 6.2831853 * float(i) / 3.0;
            float gd = abs(mod(th - arm - log(max(r, 0.02) / 0.02) / 0.3063489
                               + 3.14159265, 6.2831853) - 3.14159265);
            spiral = max(spiral, smoothstep(0.13, 0.0, gd)
                                * step(r, (0.10 + 0.55 * spin) * gZoom));
        }
    }
    spiral *= (1.0 - brk);

    /* 5. tick ring: a cosine dash is periodic, so unlike the phi-word cut
       it has no break at the -x axis (9 o'clock) */
    float tick = 0.0;
    float tickR = R + rs + 0.036;
    if (abs(r - tickR) < 0.02) {
        float cells2 = gCol > 0.5 ? 34.0 : 21.0;
        float dash = 0.5 + 0.5 * cos(cells2 * th);
        float tickOn = smoothstep(0.80, 0.90, grow) * vis * (1.0 - brk);
        tick = smoothstep(0.86, 0.97, dash)
             * smoothstep(0.004, 0.0, abs(r - tickR))
             * tickOn;
    }

    /* 6. phyllotaxis seed head in the standing centre */
    float seedOn = smoothstep(0.88, 0.96, grow) * vis * (1.0 - 0.7 * brk);
    if (seedOn > 0.002 && r < 0.14) {
        for (int k = 0; k < 8; k++) {
            float fk = float(k) + 0.5;
            float rad = rv * 0.80 * sqrt(fk / 8.0);
            float ang = fk * 2.39996323 + t * 0.04;
            seeds = max(seeds, nvLine(sdRing(q, rad * vec2(cos(ang),
                                                           sin(ang)),
                                            0.0036), 0.0015) * seedOn);
        }
    }

    /* vortex math: the baked nine-point circuit sprite (R = doubling
       circuit, G = 3-6-9 axis, B = nodes); only the global pulse remains.
       The art lives inside the unit circle, so the radius gate skips the
       fetch for most pixels. */
    float Rv = (0.30 + 0.08 * bass) * gZoom;
    if (vv > 0.002 && r < Rv * 1.08) {
        float vr = t * 0.15;
        vec2 lv = mat2(cos(-vr), -sin(-vr), sin(-vr), cos(-vr)) * q / Rv;
        vec4 tv = texture(iChannel4, lv * 0.4166667 + 0.5);
        vortex = tv.r * (0.55 + 0.45 * sin(t * 1.6));
        axis = tv.g * (0.60 + 0.40 * beat);
        vnodes = tv.b;
    }

    /* gnostic seals: seven seals on a heptagram; the story opens them one
       by one and the current seal breaks during a transition.  At the full
       dimension the Seal of Solomon (hexagram) marks the pleroma.  The
       layer is skipped while no seal is visible. */
    float sealIdx = clamp(iStory.z, 0.0, 6.0);
    if (sealVis > 0.002) {
        float Rs = (0.50 + 0.06 * bass) * gZoom;
        float sr = t * 0.09 + brk * 0.40;
        for (int k = 0; k < 7; k++) {
            float fk = float(k);
            vec2 sp = nvSealNode(fk, Rs, sr);
            float open = smoothstep(fk - 0.6, fk + 0.4, sealIdx + 0.5);
            if (abs(r - Rs) < 0.03)
                seals = max(seals, nvLine(sdRing(q, sp, 0.013), 0.0030)
                                  * mix(0.20, 1.0, open));
        }
        /* the heptagram chords are the baked sprite; the nodes above stay
           per-pixel so their open state is live.  The chords stay inside
           the heptagon, so the radius gate skips the fetch outside it. */
        if (r < Rs * 1.05) {
            vec2 ls = mat2(cos(-sr), -sin(-sr), sin(-sr), cos(-sr)) * q / Rs;
            hept = texture(iChannel2, ls * 0.4166667 + 0.5).r
                 * sealVis * (1.0 - brk * 0.6);
        }
        float hexVis = smoothstep(5.5, 6.0, nd);
        if (hexVis > 0.002) {
            for (int i = 0; i < 3; i++) {
                float a0 = 6.2831853 * float(i) / 3.0 + 1.5707963;
                float a1 = 6.2831853 * (float(i) + 1.0) / 3.0 + 1.5707963;
                vec2 v0 = 0.22 * Rs * vec2(cos(a0), sin(a0));
                vec2 v1 = 0.22 * Rs * vec2(cos(a1), sin(a1));
                if (nvBox(q, v0, v1, 0.006))
                    seals = max(seals, nvLineSq(sdSegSq(q, v0, v1), 0.0022)
                                      * hexVis);
                vec2 u0 = 0.22 * Rs * vec2(cos(a0 + 3.1415926),
                                           sin(a0 + 3.1415926));
                vec2 u1 = 0.22 * Rs * vec2(cos(a1 + 3.1415926),
                                           sin(a1 + 3.1415926));
                if (nvBox(q, u0, u1, 0.006))
                    seals = max(seals, nvLineSq(sdSegSq(q, u0, u1), 0.0022)
                                      * hexVis);
            }
        }
    }

    /* 5-D penteract: the baked pentagram sprite (five nodes + chords) */
    float Rp = (0.44 + 0.05 * bass) * gZoom;
    if (pentVis > 0.002 && r < Rp * 1.05) {
        float pr = -t * 0.06 + brk * 0.40;
        vec2 lp = mat2(cos(-pr), -sin(-pr), sin(-pr), cos(-pr)) * q / Rp;
        pent = texture(iChannel3, lp * 0.4166667 + 0.5).r * pentVis;
    }

    /* 8..13-D: a rose whose petal count is the current dimension, so the
       symmetry grows without extra loops or extra trig per petal; its
       rings sit at 0.86..1.02 of Rb, so the annulus gate skips the fetch */
    float Rb = (0.58 + 0.05 * bass) * gZoom;
    if (starVis > 0.002 && abs(r - Rb * 0.94) < Rb * 0.11) {
        float qr = -t * 0.09 + brk * 0.50;
        vec2 lr = mat2(cos(-qr), -sin(-qr), sin(-qr), cos(-qr)) * q / Rb;
        star = texture(iChannel5, lr * 0.4166667 + 0.5).r * starVis;
    }

    /* 4..13-D cascade: nested Petrie crowns, each one dimension lower and
       at a larger radius; the shadow of a shadow.  |cos(n*th)| gives the
       2n points from one cosine per ring. */
    if (crownVis > 0.002) {
        float qy = 0.5 / (0.62 * gZoom);
        float sMax = max(iSO.z, iSO.w);
        for (int m = 0; m < 3; m++) {
            float fm = float(m);
            float dir = mod(fm, 2.0) < 0.5 ? 1.0 : -1.0;
            float cr = dir * t * (0.06 + 0.024 * fm) + 0.10 * beat + 0.18 * fm;
            float Rc = min(qy * sMax * (0.82 + 0.06 * fm), 0.88);
            if (abs(r - Rc * 0.94) < Rc * 0.10) {
                vec2 lc = mat2(cos(-cr), -sin(-cr), sin(-cr), cos(-cr)) * q / Rc;
                float ctex;
                if (m == 0) ctex = texture(iChannel6, lc * 0.4166667 + 0.5).r;
                else if (m == 1) ctex = texture(iChannel7, lc * 0.4166667 + 0.5).r;
                else ctex = texture(iChannel8, lc * 0.4166667 + 0.5).r;
                crown = max(crown, ctex * crownVis * (1.0 - 0.22 * fm));
            }
        }
    }
    }

    /* 13-D pleroma: the full rose, a soft halo on the seal ring */
    float pleroma = smoothstep(12.4, 13.0, nd);
    float halo = 0.0;
    if (pleroma > 0.002)
        halo = pleroma * exp(-abs(r - (0.52 + 0.05 * bass) * gZoom) * 9.0)
             * (0.30 + 0.15 * beat);

    /* vector lines: only strong ink paints, so the field never washes out */
    line *= vis;
    /* travelling flow along the strings */
    float flow = 0.5 + 0.5 * sin(r * 26.0 - t * 2.2 + th * 5.0);
    line *= 0.70 + 0.40 * flow * (0.5 + 0.5 * mid + 0.3);
    float ink = smoothstep(0.45, 0.90, line);

    /* vivid cover-driven ink */
    float hue = 0.5 + 0.5 * sin(0.9 * r + 0.35 * sin(3.0 * th + t * 0.5)
                                + t * 0.12 + gCol);
    vec3 hot = mix(gA, gB, hue);
    hot = hot * 1.70 + 0.05;
    vec3 inkCol = mix(vec3(1.0, 0.86, 0.45), hot, 0.65);
    col = mix(col, vec3(0.10, 0.08, 0.03), ink * 0.30);
    col = mix(col, inkCol, clamp(ink * gInt, 0.0, 1.0));
    col += inkCol * spiral * 0.55 * vis;
    col += inkCol * tick * 0.7;
    col += mix(inkCol, vec3(1.0), 0.3) * seeds * 0.6;

    /* vortex-math layer */
    col += vec3(1.0, 0.72, 0.20) * vortex * vv * 0.70;
    col += vec3(0.20, 0.85, 1.0) * axis * vv * 0.70;
    col += vec3(1.0, 0.95, 0.75) * vnodes * vv * 0.55;

    /* gnostic seals */
    col += vec3(1.0, 0.82, 0.35) * seals * sealVis * 0.80;
    col += vec3(0.35, 0.85, 1.0) * hept * sealVis * 0.55;
    col += vec3(1.0, 0.78, 0.30) * pent * pentVis * 0.75;
    col += vec3(0.55, 0.85, 1.0) * star * 0.80;
    col += vec3(1.0, 0.92, 0.65) * crown * 0.80;
    col += vec3(1.0, 0.95, 0.78) * halo * 0.90;

    /* polished sheen: a moving specular highlight and a white hot core.
       Integer powers use repeated squaring instead of pow() */
    vec2 hl = 0.55 * vec2(cos(t * 0.11 + 0.7), sin(t * 0.11 + 0.7));
    float sv = clamp(1.0 - length(q - hl) / 0.95, 0.0, 1.0);
    float s2 = sv * sv, s4 = s2 * s2;
    float sheen = s4 * sv;                          /* sv^5 */
    float gloss = seals + hept + pent + star + crown + vnodes
                + vortex * 0.6 + line * 0.5;
    gloss = clamp(gloss, 0.0, 1.0);
    col += vec3(1.0, 0.97, 0.90) * sheen * gloss * (0.40 + 0.25 * beat);
    float g2 = gloss * gloss, g4 = g2 * g2, g8 = g4 * g4;
    col += vec3(1.0) * g8 * 0.30;                   /* gloss^8 */

    /* break-out shockwave */
    col += vec3(0.95, 0.86, 0.58) * brk * 0.10
         * exp(-abs(r - (0.25 + 0.45 * sin(ct * 0.25))) * 30.0);

    /* standing centre */
    float centre = 1.0 - smoothstep(rv * 0.90, rv * 0.90 + 0.008, r);
    col = mix(col, field * 1.15, centre * 0.55 * vis);

    /* growth head: a bright point where the newest element is drawn */
    col += inkCol * line * beat * 0.30;
    col *= 1.0 + 0.16 * beat;                       /* pop on the beat */
    col = mix(col, mix(gA, gB, gCol), 0.03 + 0.05 * gCol);  /* cover tint */
    float lum = dot(col, vec3(0.299, 0.587, 0.114));
    col = mix(vec3(lum), col, 1.35);                /* saturation lift */
    col = max(col, vec3(0.0));
    col *= 1.0 - 0.35 * smoothstep(0.70, 1.30, length(uv));
    c = vec4(col, 1.0);
}
