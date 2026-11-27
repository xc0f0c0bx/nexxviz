/*
 * nexxvis - fullscreen GLSL audio visualizer + launcher menu overlay for nexxxen (Pi 4, KMS, no desktop)
 *
 * - renders straight to the HDMI output through DRM/GBM/EGL (GLES 3)
 * - audio: monitor of the PipeWire sink (default "speakereq2x2") via `pw-record --raw`,
 *   2048-point FFT -> 512 log bins (30 Hz..16 kHz) + 512 waveform samples
 * - shaders: Shadertoy style `void mainImage(out vec4 c, in vec2 p)` files in NV_SHADERS
 *   uniforms: iResolution, iTime, iTimeDelta, iFrame, iChannel0 (512x2: row0 = spectrum,
 *   row1 = waveform, sample at y=0.25 / 0.75), iLevel (bass, mid, treble, overall; 0..1 with AGC)
 *   shaders cycle every NV_CYCLE seconds with a fade through black; SIGHUP reloads the directory
 * - menu overlay state comes from the hub daemon in NV_MENU_FILE: "<visible 0|1> <selected index>"
 *   tile images are raw RGBA files NV_TILES/tile<N>.rgba (u32 width, u32 height, pixels), hint.rgba
 *
 * env: NV_CARD NV_CONNECTOR (e.g. HDMI-A-2) NV_MODE (1920x1080@60) NV_SCALE (0.5) NV_SHADERS
 *      NV_CYCLE (300) NV_SINK (speakereq2x2) NV_MENU_FILE NV_TILES NV_FPS_LOG (0/1)
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <signal.h>
#include <dirent.h>
#include <pthread.h>
#include <time.h>
#include <poll.h>
#include <sys/ioctl.h>
#include <sys/stat.h>
#include <linux/kd.h>
#include <xf86drm.h>
#include <xf86drmMode.h>
#include <gbm.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>

#include "beatstate.h"
#include "beatdetect.h"

#define FFT_N 2048
#define BINS 512
#define MAX_SHADERS 64
#define MAX_TILES 8

static volatile sig_atomic_t g_quit = 0, g_reload = 0;
static void on_term(int s) { (void)s; g_quit = 1; }
static void on_hup(int s) { (void)s; g_reload = 1; }

static const char *envs(const char *k, const char *d) { const char *v = getenv(k); return (v && *v) ? v : d; }
static double now_s(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec * 1e-9; }
static double now_epoch(void) { struct timespec t; clock_gettime(CLOCK_REALTIME, &t); return t.tv_sec + t.tv_nsec * 1e-9; }

/* ---- baked straw backdrop ------------------------------------------- */
static float fr(float x) { return x - floorf(x); }
static float h2(float x, float y) {
    float px = fr(x * 0.1031f), py = fr(y * 0.1031f), pz = px;
    float d = px * (py + 33.33f) + py * (pz + 33.33f) + pz * (px + 33.33f);
    px += d; py += d; pz += d;
    return fr((px + py) * pz);
}
static float n2(float x, float y) {
    float ix = floorf(x), iy = floorf(y);
    float fx = x - ix, fy = y - iy;
    fx = fx * fx * (3.0f - 2.0f * fx);
    fy = fy * fy * (3.0f - 2.0f * fy);
    float a = h2(ix, iy), b = h2(ix + 1.0f, iy);
    float c = h2(ix, iy + 1.0f), d = h2(ix + 1.0f, iy + 1.0f);
    float ab = a + (b - a) * fx, cd = c + (d - c) * fx;
    return ab + (cd - ab) * fy;
}
static float ss(float a, float b, float x) {
    float t = (x - a) / (b - a);
    t = t < 0 ? 0 : (t > 1 ? 1 : t);
    return t * t * (3.0f - 2.0f * t);
}
static GLuint make_straw(int N) {
    unsigned char *px = malloc((size_t)N * N * 4);
    if (!px) return 0;
    const float R = 2.4f;
    for (int y = 0; y < N; y++) {
        for (int x = 0; x < N; x++) {
            float qx = ((x + 0.5f) / N * 2.0f - 1.0f) * R;
            float qy = ((y + 0.5f) / N * 2.0f - 1.0f) * R;
            float fn = n2(qx * 2.7f, qy * 2.7f);
            float row = 0.5f + 0.5f * sinf(qx * 80.0f + qy * 28.0f + 2.2f * fn);
            float br = 0.90f + 0.18f * fn;
            float cr = (0.12f + 0.12f * row) * br;
            float cg = (0.08f + 0.09f * row) * br;
            float cb = (0.03f + 0.04f * row) * br;
            float m = ss(0.70f, 1.05f, sqrtf(qx * qx + qy * qy)) * 0.5f;
            cr += (0.10f - cr) * m;
            cg += (0.14f - cg) * m;
            cb += (0.04f - cb) * m;
            unsigned char *p = px + ((size_t)y * N + x) * 4;
            p[0] = (unsigned char)(cr < 0 ? 0 : (cr > 1 ? 255 : cr * 255.0f));
            p[1] = (unsigned char)(cg < 0 ? 0 : (cg > 1 ? 255 : cg * 255.0f));
            p[2] = (unsigned char)(cb < 0 ? 0 : (cb > 1 ? 255 : cb * 255.0f));
            p[3] = 255;
        }
    }
    GLuint t; glGenTextures(1, &t); glBindTexture(GL_TEXTURE_2D, t);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, N, N, 0, GL_RGBA, GL_UNSIGNED_BYTE, px);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
    free(px);
    return t;
}

/* the flat-disk swirl pattern: sin/cos of th*6 + r*55 + 1.2*noise(q*5)
   baked once, so the shader replaces a 4-hash noise plus a sine per pixel
   with one texture fetch and a phase rotation */
static GLuint make_swirl(int N) {
    unsigned char *px = malloc((size_t)N * N * 4);
    if (!px) return 0;
    const float R = 1.0f;
    for (int y = 0; y < N; y++) {
        for (int x = 0; x < N; x++) {
            float qx = ((x + 0.5f) / N * 2.0f - 1.0f) * R;
            float qy = ((y + 0.5f) / N * 2.0f - 1.0f) * R;
            float th = atan2f(qy, qx);
            float r = sqrtf(qx * qx + qy * qy);
            float P = th * 6.0f + r * 55.0f + 1.2f * n2(qx * 5.0f, qy * 5.0f);
            unsigned char *p = px + ((size_t)y * N + x) * 4;
            p[0] = (unsigned char)((0.5f + 0.5f * sinf(P)) * 255.0f);
            p[1] = (unsigned char)((0.5f + 0.5f * cosf(P)) * 255.0f);
            p[2] = 0; p[3] = 255;
        }
    }
    GLuint t; glGenTextures(1, &t); glBindTexture(GL_TEXTURE_2D, t);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, N, N, 0, GL_RGBA, GL_UNSIGNED_BYTE, px);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
    free(px);
    return t;
}

/* ---- baked layer sprites -------------------------------------------- */
static float sdc(float x, float y, float cx, float cy, float r) {
    float dx = x - cx, dy = y - cy;
    return sqrtf(dx * dx + dy * dy) - r;
}
static float sds(float x, float y, float ax, float ay, float bx, float by) {
    float pax = x - ax, pay = y - ay, bax = bx - ax, bay = by - ay;
    float h = (pax * bax + pay * bay) / (bax * bax + bay * bay + 1e-9f);
    h = h < 0 ? 0 : (h > 1 ? 1 : h);
    float dx = pax - bax * h, dy = pay - bay * h;
    return sqrtf(dx * dx + dy * dy);
}
static float lnf(float d, float w, float aa) {
    float a = fabsf(d) - w;
    if (a >= aa) return 0.0f;
    if (a < 0.0f) a = 0.0f;
    float t = a / aa;
    return 1.0f - t * t * (3.0f - 2.0f * t);
}
static GLuint bake_art(int N, int kind) {    unsigned char *px = calloc((size_t)N * N, 4);
    if (!px) return 0;
    const float R = 1.2f;
    for (int y = 0; y < N; y++) {
        for (int x = 0; x < N; x++) {
            float qx = ((x + 0.5f) / N * 2.0f - 1.0f) * R;
            float qy = ((y + 0.5f) / N * 2.0f - 1.0f) * R;
            float mr = 0, mg = 0, mb = 0;
            if (kind == 0) {            /* heptagram chords, unit circle */
                for (int k = 0; k < 7; k++) {
                    float a0 = 6.2831853f * k / 7.0f + 1.5707963f;
                    float a1 = 6.2831853f * ((k + 3) % 7) / 7.0f + 1.5707963f;
                    mr = fmaxf(mr, lnf(sds(qx, qy, cosf(a0), sinf(a0),
                                           cosf(a1), sinf(a1)), 0.0036f, 0.0032f));
                }
            } else if (kind == 1) {     /* pentagram: nodes + chords */
                for (int k = 0; k < 5; k++) {
                    float a0 = 6.2831853f * k / 5.0f + 1.5707963f;
                    float a1 = 6.2831853f * ((k + 2) % 5) / 5.0f + 1.5707963f;
                    float cx = cosf(a0), cy = sinf(a0);
                    mr = fmaxf(mr, lnf(fabsf(sdc(qx, qy, cx, cy, 0.0f)) - 0.0227f,
                                       0.0064f, 0.0036f));
                    mr = fmaxf(mr, lnf(sds(qx, qy, cx, cy,
                                           cosf(a1), sinf(a1)), 0.0041f, 0.0032f));
                }
            } else {                    /* vortex: R chords, G axis, B nodes */
                for (int k = 1; k <= 9; k++) {
                    float a = 6.2831853f * k / 9.0f + 1.5707963f;
                    mb = fmaxf(mb, lnf(fabsf(sdc(qx, qy, cosf(a), sinf(a), 0.0f))
                                       - 0.0289f, 0.0079f, 0.0036f));
                }
                const int dbl[6][2] = {{1,2},{2,4},{4,8},{8,7},{7,5},{5,1}};
                for (int i = 0; i < 6; i++) {
                    float a0 = 6.2831853f * dbl[i][0] / 9.0f + 1.5707963f;
                    float a1 = 6.2831853f * dbl[i][1] / 9.0f + 1.5707963f;
                    mr = fmaxf(mr, lnf(sds(qx, qy, cosf(a0), sinf(a0),
                                           cosf(a1), sinf(a1)), 0.0063f, 0.0032f));
                }
                const int ax[3][2] = {{3,6},{6,9},{9,3}};
                for (int i = 0; i < 3; i++) {
                    float a0 = 6.2831853f * ax[i][0] / 9.0f + 1.5707963f;
                    float a1 = 6.2831853f * ax[i][1] / 9.0f + 1.5707963f;
                    mg = fmaxf(mg, lnf(sds(qx, qy, cosf(a0), sinf(a0),
                                           cosf(a1), sinf(a1)), 0.0068f, 0.0032f));
                }
            }
            unsigned char *p = px + ((size_t)y * N + x) * 4;
            p[0] = (unsigned char)(mr > 1 ? 255 : mr * 255);
            p[1] = (unsigned char)(mg > 1 ? 255 : mg * 255);
            p[2] = (unsigned char)(mb > 1 ? 255 : mb * 255);
            p[3] = 255;
        }
    }
    GLuint t; glGenTextures(1, &t); glBindTexture(GL_TEXTURE_2D, t);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, N, N, 0, GL_RGBA, GL_UNSIGNED_BYTE, px);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
    free(px);
    return t;
}

/* ---- per-dimension rose and crown sprites --------------------------- */
static GLuint dyntex[4];
static int dyntex_init = 0;

#define DYN_N 512

/* CPU fill of the four layers into one buffer; the render thread never
   touches the buffer while the worker fills it */
static void dyn_fill(int n, unsigned char *px) {
    const int N = DYN_N;
    const float R = 1.2f;
    for (int layer = 0; layer < 4; layer++) {
        /* layer 0 is the rose (n petals); layers 1..3 are the cascade
           crowns at n, n-2, n-4, matching the shader's m loop */
        float nm = layer == 0 ? (float)n
                              : fmaxf((float)n - 2.0f * (float)(layer - 1), 3.0f);
        unsigned char *base = px + (size_t)layer * N * N * 4;
        for (int y = 0; y < N; y++) {
            for (int x = 0; x < N; x++) {
                float qx = ((x + 0.5f) / N * 2.0f - 1.0f) * R;
                float qy = ((y + 0.5f) / N * 2.0f - 1.0f) * R;
                float th = atan2f(qy, qx);
                float r = sqrtf(qx * qx + qy * qy);
                float m;
                if (layer == 0) {
                    float p = 0.5f + 0.5f * cosf(nm * th);
                    m = fmaxf(lnf(r - (0.92f + 0.10f * p), 0.0045f, 0.0031f),
                              lnf(r - (0.86f + 0.14f * p), 0.0031f, 0.0022f));
                } else {
                    float c = fabsf(cosf(nm * th));
                    float c2 = c * c, c4 = c2 * c2, c6 = c4 * c2;
                    m = lnf(r - (0.88f + 0.12f * c6), 0.0031f, 0.0022f);
                }
                unsigned char *p = base + ((size_t)y * N + x) * 4;
                p[0] = (unsigned char)(m > 1 ? 255 : m * 255);
                p[1] = 0; p[2] = 0; p[3] = 255;
            }
        }
    }
}

static void dyn_init(void) {
    if (dyntex_init) return;
    glGenTextures(4, dyntex);
    for (int i = 0; i < 4; i++) {
        glBindTexture(GL_TEXTURE_2D, dyntex[i]);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, DYN_N, DYN_N, 0, GL_RGBA,
                     GL_UNSIGNED_BYTE, NULL);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    }
    dyntex_init = 1;
}

static void dyn_upload(const unsigned char *px) {
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    for (int i = 0; i < 4; i++) {
        glBindTexture(GL_TEXTURE_2D, dyntex[i]);
        glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, DYN_N, DYN_N, GL_RGBA,
                        GL_UNSIGNED_BYTE, px + (size_t)i * DYN_N * DYN_N * 4);
    }
    glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
}

/* async rebake: the fill runs on a worker core, the upload on the render
   thread, so a chapter change no longer stalls a frame */
static pthread_t dyn_thr;
static pthread_mutex_t dyn_mtx = PTHREAD_MUTEX_INITIALIZER;
static int dyn_busy = 0, dyn_ready = 0, dyn_n = 0;
static unsigned char *dyn_px = NULL;
static double dyn_fill_ms = 0, dyn_up_ms = 0;

static void *dyn_worker(void *arg) {
    int n = (int)(intptr_t)arg;
    struct timespec b0, b1;
    clock_gettime(CLOCK_MONOTONIC, &b0);
    dyn_fill(n, dyn_px);
    clock_gettime(CLOCK_MONOTONIC, &b1);
    dyn_fill_ms = (b1.tv_sec - b0.tv_sec) * 1e3
                + (b1.tv_nsec - b0.tv_nsec) / 1e6;
    pthread_mutex_lock(&dyn_mtx);
    dyn_ready = 1;
    pthread_mutex_unlock(&dyn_mtx);
    return NULL;
}

static int dyn_start(int n) {
    if (!dyn_px) dyn_px = malloc((size_t)DYN_N * DYN_N * 4 * 4);
    if (!dyn_px) return 0;
    dyn_n = n;
    dyn_up_ms = 0;
    dyn_ready = 0;
    dyn_busy = 1;
    if (pthread_create(&dyn_thr, NULL, dyn_worker, (void *)(intptr_t)n) != 0) {
        dyn_busy = 0;
        return 0;
    }
    pthread_detach(dyn_thr);
    return 1;
}

/* call once per frame: uploads a finished bake into all four textures at
   once (51 ms) rather than one per frame; splitting it makes every frame
   wait on the previous frame's GPU work and costs far more */
static int dyn_finish(void) {
    int ready;
    pthread_mutex_lock(&dyn_mtx);
    ready = dyn_ready;
    pthread_mutex_unlock(&dyn_mtx);
    if (!ready) return 0;
    struct timespec b0, b1;
    clock_gettime(CLOCK_MONOTONIC, &b0);
    dyn_upload(dyn_px);
    clock_gettime(CLOCK_MONOTONIC, &b1);
    dyn_up_ms = (b1.tv_sec - b0.tv_sec) * 1e3
              + (b1.tv_nsec - b0.tv_nsec) / 1e6;
    free(dyn_px);
    dyn_px = NULL;
    dyn_ready = 0;
    dyn_busy = 0;
    fprintf(stderr, "nexxvis: bake_dyn %d in %.0f ms fill + %.0f ms upload (async)\n",
            dyn_n, dyn_fill_ms, dyn_up_ms);
    return 1;
}

/* synchronous bake, startup only */
static void bake_dyn(int n) {
    struct timespec tb0, tb1;
    clock_gettime(CLOCK_MONOTONIC, &tb0);
    dyn_init();
    unsigned char *px = malloc((size_t)DYN_N * DYN_N * 4 * 4);
    if (!px) return;
    dyn_fill(n, px);
    dyn_upload(px);
    free(px);
    clock_gettime(CLOCK_MONOTONIC, &tb1);
    fprintf(stderr, "nexxvis: bake_dyn %d in %.0f ms\n", n,
            (tb1.tv_sec - tb0.tv_sec) * 1e3
            + (tb1.tv_nsec - tb0.tv_nsec) / 1e6);
}

/* ------------------------------------------------------------------ audio */
static pthread_mutex_t a_mtx = PTHREAD_MUTEX_INITIALIZER;
static float a_ring[FFT_N];      /* mono, most recent FFT_N samples */
static int a_pos = 0;
static double a_last = 0;        /* time of last received block */

static void *audio_thread(void *arg) {
    const char *sink = (const char *)arg;
    char cmd[512];
    snprintf(cmd, sizeof cmd,
             "exec pw-record --raw --target '%s' -P '{ stream.capture.sink = true, node.name = nexxvis-capture, "
             "media.role = Music }' --rate 48000 --channels 2 --format f32 --latency 20ms - 2>/dev/null", sink);
    while (!g_quit) {
        FILE *p = popen(cmd, "r");
        if (!p) { sleep(2); continue; }
        float buf[2 * 256];
        while (!g_quit) {
            size_t n = fread(buf, sizeof(float) * 2, 256, p);
            if (n == 0) break;
            pthread_mutex_lock(&a_mtx);
            for (size_t i = 0; i < n; i++) {
                a_ring[a_pos] = 0.5f * (buf[2 * i] + buf[2 * i + 1]);
                a_pos = (a_pos + 1) & (FFT_N - 1);
            }
            a_last = now_s();
            pthread_mutex_unlock(&a_mtx);
        }
        pclose(p);
        if (!g_quit) sleep(2);   /* PipeWire restarted / sink missing: retry */
    }
    return NULL;
}

/* radix-2 complex FFT in place */
static void fft(float *re, float *im, int n) {
    for (int i = 1, j = 0; i < n; i++) {
        int bit = n >> 1;
        for (; j & bit; bit >>= 1) j ^= bit;
        j ^= bit;
        if (i < j) { float t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; }
    }
    for (int len = 2; len <= n; len <<= 1) {
        float ang = -2.0f * (float)M_PI / len;
        float wr = cosf(ang), wi = sinf(ang);
        for (int i = 0; i < n; i += len) {
            float cr = 1, ci = 0;
            for (int k = 0; k < len / 2; k++) {
                int a = i + k, b = i + k + len / 2;
                float tr = re[b] * cr - im[b] * ci, ti = re[b] * ci + im[b] * cr;
                re[b] = re[a] - tr; im[b] = im[a] - ti;
                re[a] += tr; im[a] += ti;
                float ncr = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = ncr;
            }
        }
    }
}

typedef struct {
    float spec[BINS], wave[BINS];
    float level[4];
    float agc[4];
    int bin_lo[BINS], bin_hi[BINS];
    unsigned char bin_band[BINS], bin_b8[BINS];  /* precomputed groups */
    float window[FFT_N];
    float mag[BD_MAX_BINS];
    /* eight perceptual bands + detected elements */
    float band8[8], band8_agc[8], band8_prev[8], band8_level[8], band8_flux[8];
    float elem[4];   /* kick, snare, hat, vocal */
} Analysis;

static void analysis_init(Analysis *A) {
    memset(A, 0, sizeof *A);
    for (int i = 0; i < FFT_N; i++) A->window[i] = 0.5f - 0.5f * cosf(2.0f * (float)M_PI * i / (FFT_N - 1));
    const float fmin = 30.0f, fmax = 16000.0f, hz_per_bin = 48000.0f / FFT_N;
    for (int b = 0; b < BINS; b++) {
        float f0 = fmin * powf(fmax / fmin, (float)b / BINS);
        float f1 = fmin * powf(fmax / fmin, (float)(b + 1) / BINS);
        int lo = (int)floorf(f0 / hz_per_bin), hi = (int)ceilf(f1 / hz_per_bin);
        if (lo < 1) lo = 1;
        if (hi <= lo) hi = lo + 1;
        if (hi > FFT_N / 2) hi = FFT_N / 2;
        A->bin_lo[b] = lo; A->bin_hi[b] = hi;
        /* the group of each log bin never changes: precompute it so the
           frame loop does not call powf() 512 times per frame */
        float f = fmin * powf(fmax / fmin, (b + 0.5f) / BINS);
        A->bin_band[b] = f < 150.0f ? 0 : (f < 2000.0f ? 1 : 2);
        A->bin_b8[b] = f < 60.0f ? 0 : f < 120.0f ? 1 : f < 250.0f ? 2
                     : f < 500.0f ? 3 : f < 1000.0f ? 4 : f < 2500.0f ? 5
                     : f < 6000.0f ? 6 : 7;
    }
    for (int i = 0; i < 4; i++) A->agc[i] = 0.05f;
    for (int i = 0; i < 8; i++) A->band8_agc[i] = 0.05f;
}

static int analysis_update(Analysis *A, float dt) {
    static float re[FFT_N], im[FFT_N], mono[FFT_N];
    double last;
    pthread_mutex_lock(&a_mtx);
    for (int i = 0; i < FFT_N; i++) mono[i] = a_ring[(a_pos + i) & (FFT_N - 1)];
    last = a_last;
    pthread_mutex_unlock(&a_mtx);
    int stale = (now_s() - last) > 0.5;        /* no audio flowing -> decay to silence */
    for (int i = 0; i < FFT_N; i++) { re[i] = stale ? 0 : mono[i] * A->window[i]; im[i] = 0; }
    fft(re, im, FFT_N);
    for (int k = 0; k < BD_MAX_BINS; k++) {
        float v = re[k + 1] * re[k + 1] + im[k + 1] * im[k + 1];
        A->mag[k] = sqrtf(v);
    }

    float attack = 1.0f - expf(-dt / 0.03f), release = 1.0f - expf(-dt / 0.25f);
    float band[3] = {0, 0, 0}; int bandn[3] = {0, 0, 0};
    float b8[8] = {0}; int b8n[8] = {0};
    for (int b = 0; b < BINS; b++) {
        float m = 0;
        for (int k = A->bin_lo[b]; k < A->bin_hi[b]; k++) { float v = re[k] * re[k] + im[k] * im[k]; if (v > m) m = v; }
        float db = 10.0f * log10f(m + 1e-12f) - 20.0f * log10f(FFT_N / 4.0f);
        float v = (db + 72.0f) / 66.0f;               /* -72..-6 dBFS -> 0..1 */
        v = v < 0 ? 0 : (v > 1 ? 1 : v);
        float k = v > A->spec[b] ? attack : release;
        A->spec[b] += (v - A->spec[b]) * k;
        int bi = A->bin_band[b];
        band[bi] += A->spec[b]; bandn[bi]++;
        int bj = A->bin_b8[b];
        b8[bj] += A->spec[b]; b8n[bj]++;
    }
    for (int i = 0; i < BINS; i++) {
        float s = stale ? 0 : mono[FFT_N - BINS + i];
        A->wave[i] = 0.5f + 0.5f * (s > 1 ? 1 : (s < -1 ? -1 : s));
    }
    float raw[4];
    for (int i = 0; i < 3; i++) raw[i] = bandn[i] ? band[i] / bandn[i] : 0;
    raw[3] = (raw[0] + raw[1] + raw[2]) / 3.0f;
    for (int i = 0; i < 4; i++) {       /* slow AGC so visuals work at any source level */
        float target = raw[i] > A->agc[i] ? raw[i] : A->agc[i] * (1.0f - dt / 20.0f);
        A->agc[i] = target < 0.05f ? 0.05f : target;
        float v = raw[i] / A->agc[i];
        v = v * v;
        float k = v > A->level[i] ? attack : release;
        A->level[i] += ((v > 1 ? 1 : v) - A->level[i]) * k;
    }

    /* eight perceptual bands, each with its own slow AGC and fast flux */
    for (int j = 0; j < 8; j++) {
        float rawb = b8n[j] ? b8[j] / b8n[j] : 0.0f;
        float target = rawb > A->band8_agc[j] ? rawb
                     : A->band8_agc[j] * (1.0f - dt / 20.0f);
        A->band8_agc[j] = target < 0.05f ? 0.05f : target;
        float v = rawb / A->band8_agc[j];
        v = v * v;
        if (v > 1.0f) v = 1.0f;
        float k = v > A->band8_level[j] ? attack : release;
        A->band8_level[j] += (v - A->band8_level[j]) * k;
        float fl = A->band8_level[j] - A->band8_prev[j];
        A->band8_flux[j] = fl > 0.0f ? fl : 0.0f;
        A->band8_prev[j] = A->band8_level[j];
    }

    /* musical elements: onset + band energy, fast attack / medium release */
    float eatk = 1.0f - expf(-dt / 0.012f), erel = 1.0f - expf(-dt / 0.20f);
    float et[4];
    et[0] = A->band8_level[1] * 0.85f + A->band8_flux[1] * 7.0f;      /* kick */
    et[1] = A->band8_level[5] * 0.55f + A->band8_flux[5] * 5.0f
          + A->band8_flux[6] * 2.5f;                                   /* snare */
    et[2] = A->band8_level[7] * 0.70f + A->band8_flux[7] * 6.0f;      /* hats */
    et[3] = A->band8_level[3] * 0.60f + A->band8_level[4] * 0.40f;    /* vocal */
    for (int i = 0; i < 4; i++) {
        float v = et[i] < 0.0f ? 0.0f : (et[i] > 1.0f ? 1.0f : et[i]);
        float k = v > A->elem[i] ? eatk : erel;
        A->elem[i] += (v - A->elem[i]) * k;
    }
    return stale;
}

/* ------------------------------------------------------------------ DRM / GBM / EGL */
typedef struct {
    int fd;
    uint32_t conn_id, crtc_id;
    drmModeModeInfo mode;
    struct gbm_device *gbm;
    struct gbm_surface *surf;
    EGLDisplay dpy; EGLContext ctx; EGLSurface es;
    struct gbm_bo *shown_bo;     /* on screen */
    struct gbm_bo *queued_bo;    /* flip requested, not yet on screen */
    int flip_pending, crtc_set;
} Kms;

static const char *conn_type_name(uint32_t t) {
    switch (t) {
        case DRM_MODE_CONNECTOR_HDMIA: return "HDMI-A";
        case DRM_MODE_CONNECTOR_HDMIB: return "HDMI-B";
        case DRM_MODE_CONNECTOR_DSI: return "DSI";
        case DRM_MODE_CONNECTOR_Composite: return "Composite";
        case DRM_MODE_CONNECTOR_DPI: return "DPI";
        case DRM_MODE_CONNECTOR_VIRTUAL: return "Virtual";
        default: return "Unknown";
    }
}

static int kms_init(Kms *K, const char *card, const char *want_conn, int want_w, int want_h, int want_hz) {
    memset(K, 0, sizeof *K);
    K->fd = open(card, O_RDWR | O_CLOEXEC);
    if (K->fd < 0) { perror(card); return -1; }
    drmModeRes *res = drmModeGetResources(K->fd);
    if (!res) { fprintf(stderr, "drmModeGetResources failed\n"); return -1; }
    drmModeConnector *conn = NULL;
    for (int i = 0; i < res->count_connectors; i++) {
        drmModeConnector *c = drmModeGetConnector(K->fd, res->connectors[i]);
        if (!c) continue;
        char name[32]; snprintf(name, sizeof name, "%s-%u", conn_type_name(c->connector_type), c->connector_type_id);
        int ok = c->connection == DRM_MODE_CONNECTED && c->count_modes > 0;
        if (ok && (!want_conn || !*want_conn || strcmp(want_conn, name) == 0)) { conn = c; fprintf(stderr, "nexxvis: connector %s\n", name); break; }
        drmModeFreeConnector(c);
    }
    if (!conn) { fprintf(stderr, "nexxvis: no connected connector %s\n", want_conn ? want_conn : ""); return -1; }
    K->conn_id = conn->connector_id;
    int best = -1;
    for (int i = 0; i < conn->count_modes; i++) {
        drmModeModeInfo *m = &conn->modes[i];
        if (m->hdisplay == want_w && m->vdisplay == want_h && (want_hz == 0 || (int)m->vrefresh == want_hz)) {
            if (best < 0 || (m->flags & DRM_MODE_FLAG_INTERLACE) == 0) best = i;
            if ((m->flags & DRM_MODE_FLAG_INTERLACE) == 0) break;
        }
    }
    if (best < 0) for (int i = 0; i < conn->count_modes; i++) if (conn->modes[i].type & DRM_MODE_TYPE_PREFERRED) { best = i; break; }
    if (best < 0) best = 0;
    K->mode = conn->modes[best];
    fprintf(stderr, "nexxvis: mode %ux%u@%u\n", K->mode.hdisplay, K->mode.vdisplay, K->mode.vrefresh);

    /* pick a CRTC usable by one of the connector's encoders */
    K->crtc_id = 0;
    for (int e = 0; e < conn->count_encoders && !K->crtc_id; e++) {
        drmModeEncoder *enc = drmModeGetEncoder(K->fd, conn->encoders[e]);
        if (!enc) continue;
        if (enc->crtc_id) K->crtc_id = enc->crtc_id;
        else for (int c = 0; c < res->count_crtcs; c++) if (enc->possible_crtcs & (1u << c)) { K->crtc_id = res->crtcs[c]; break; }
        drmModeFreeEncoder(enc);
    }
    drmModeFreeConnector(conn); drmModeFreeResources(res);
    if (!K->crtc_id) { fprintf(stderr, "nexxvis: no CRTC\n"); return -1; }

    K->gbm = gbm_create_device(K->fd);
    K->surf = gbm_surface_create(K->gbm, K->mode.hdisplay, K->mode.vdisplay, GBM_FORMAT_XRGB8888,
                                 GBM_BO_USE_SCANOUT | GBM_BO_USE_RENDERING);
    if (!K->surf) { fprintf(stderr, "gbm_surface_create failed\n"); return -1; }

    PFNEGLGETPLATFORMDISPLAYEXTPROC gpd = (PFNEGLGETPLATFORMDISPLAYEXTPROC)eglGetProcAddress("eglGetPlatformDisplayEXT");
    K->dpy = gpd ? gpd(EGL_PLATFORM_GBM_KHR, K->gbm, NULL) : eglGetDisplay((EGLNativeDisplayType)K->gbm);
    if (!eglInitialize(K->dpy, NULL, NULL)) { fprintf(stderr, "eglInitialize failed\n"); return -1; }
    eglBindAPI(EGL_OPENGL_ES_API);
    EGLint cattr[] = {EGL_SURFACE_TYPE, EGL_WINDOW_BIT, EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8,
                      EGL_ALPHA_SIZE, 0, EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT, EGL_NONE};
    EGLint n = 0; EGLConfig cfgs[64], cfg = NULL;
    eglChooseConfig(K->dpy, cattr, cfgs, 64, &n);
    for (int i = 0; i < n; i++) {
        EGLint vid; eglGetConfigAttrib(K->dpy, cfgs[i], EGL_NATIVE_VISUAL_ID, &vid);
        if (vid == GBM_FORMAT_XRGB8888) { cfg = cfgs[i]; break; }
    }
    if (!cfg) { fprintf(stderr, "no matching EGL config\n"); return -1; }
    EGLint xattr[] = {EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE};
    K->ctx = eglCreateContext(K->dpy, cfg, EGL_NO_CONTEXT, xattr);
    K->es = eglCreateWindowSurface(K->dpy, cfg, (EGLNativeWindowType)K->surf, NULL);
    if (!K->ctx || K->es == EGL_NO_SURFACE) { fprintf(stderr, "EGL context/surface failed\n"); return -1; }
    eglMakeCurrent(K->dpy, K->es, K->es, K->ctx);
    eglSwapInterval(K->dpy, atoi(envs("NV_SWAP_INTERVAL", "1")));
    return 0;
}

static void page_flip_handler(int fd, unsigned int f, unsigned int s, unsigned int us, void *data) {
    (void)fd; (void)f; (void)s; (void)us; *(int *)data = 0;
}

static void bo_destroy_cb(struct gbm_bo *bo, void *data) {
    int fd = gbm_device_get_fd(gbm_bo_get_device(bo));
    uint32_t fb = (uint32_t)(uintptr_t)data;
    if (fb) drmModeRmFB(fd, fb);
}

static uint32_t bo_fb(Kms *K, struct gbm_bo *bo) {
    uint32_t fb = (uint32_t)(uintptr_t)gbm_bo_get_user_data(bo);
    if (fb) return fb;
    uint32_t handles[4] = {gbm_bo_get_handle(bo).u32}, pitches[4] = {gbm_bo_get_stride(bo)}, offs[4] = {0};
    if (drmModeAddFB2(K->fd, gbm_bo_get_width(bo), gbm_bo_get_height(bo), GBM_FORMAT_XRGB8888, handles, pitches, offs, &fb, 0)) {
        fprintf(stderr, "drmModeAddFB2 failed: %s\n", strerror(errno));
        return 0;
    }
    gbm_bo_set_user_data(bo, (void *)(uintptr_t)fb, bo_destroy_cb);
    return fb;
}

/* wait until the requested flip is on screen, then recycle the buffer it replaced */
static void kms_wait_flip(Kms *K) {
    drmEventContext ev = {.version = 2, .page_flip_handler = page_flip_handler};
    while (K->flip_pending && !g_quit) {
        struct pollfd pfd = {.fd = K->fd, .events = POLLIN};
        if (poll(&pfd, 1, 100) > 0) drmHandleEvent(K->fd, &ev);
    }
    if (K->queued_bo) {
        if (K->shown_bo) gbm_surface_release_buffer(K->surf, K->shown_bo);
        K->shown_bo = K->queued_bo;
        K->queued_bo = NULL;
    }
}

/* Pipelined present: the flip for frame N is queued and we return immediately, so frame N+1
 * renders while N waits for vblank (three buffers in flight: shown, queued, rendering).
 * With the old wait-right-after-flip loop a frame that took just over 16.7 ms dropped to 30 fps. */
static int kms_present(Kms *K) {
    eglSwapBuffers(K->dpy, K->es);
    kms_wait_flip(K);                       /* previous flip must land before we queue another */
    struct gbm_bo *bo = gbm_surface_lock_front_buffer(K->surf);
    if (!bo) return -1;
    uint32_t fb = bo_fb(K, bo);
    if (!K->crtc_set) {
        if (drmModeSetCrtc(K->fd, K->crtc_id, fb, 0, 0, &K->conn_id, 1, &K->mode)) {
            fprintf(stderr, "drmModeSetCrtc failed: %s (DRM master held by someone else?)\n", strerror(errno));
            gbm_surface_release_buffer(K->surf, bo);
            return -1;
        }
        K->crtc_set = 1;
        K->shown_bo = bo;
        return 0;
    }
    K->flip_pending = 1;
    if (drmModePageFlip(K->fd, K->crtc_id, fb, DRM_MODE_PAGE_FLIP_EVENT, &K->flip_pending)) {
        fprintf(stderr, "drmModePageFlip failed: %s\n", strerror(errno));
        K->flip_pending = 0;
        gbm_surface_release_buffer(K->surf, bo);
        return 0;
    }
    K->queued_bo = bo;
    return 0;
}

/* ------------------------------------------------------------------ GL helpers */
static const char *VS =
    "#version 300 es\n"
    "layout(location=0) in vec2 p; out vec2 uv;\n"
    "uniform vec4 rect; /* x,y,w,h in NDC */\n"
    "void main(){ uv = p; gl_Position = vec4(rect.xy + p*rect.zw, 0.0, 1.0); }\n";

static const char *FS_HEAD =
    "#version 300 es\n"
    "precision highp float;\n"
    "uniform vec3 iResolution; uniform float iTime; uniform float iTimeDelta; uniform int iFrame;\n"
    "uniform sampler2D iChannel0; uniform sampler2D iChannel1; uniform sampler2D iChannel2; uniform sampler2D iChannel3; uniform sampler2D iChannel4; uniform sampler2D iChannel5; uniform sampler2D iChannel6; uniform sampler2D iChannel7; uniform sampler2D iChannel8; uniform sampler2D iChannel9; uniform vec4 iLevel;\n"
    "uniform vec4 iBeat; /* pulse, phase, source 0/1/2, confidence */\n"
    "uniform float iBPM;\n"
    "uniform vec3 iCoverA; uniform vec3 iCoverB;\n"
    "uniform vec4 iGenomeA; uniform vec4 iGenomeB;\n"
    "uniform vec4 iEntropy; /* /dev/urandom: fresh 0..1 values per generation */\n"
    "uniform vec4 iStory; /* dim, transition, chapter phase, energy */\n"
    "uniform vec4 iSO; /* cos a4, sin a4, sx, sy: SO(n) shadow */\n"
    "uniform vec4 iElements; /* kick, snare, hat, vocal */\n"
    "uniform vec4 iBandA; /* sub, kick, low-mid, mid */\n"
    "uniform vec4 iBandB; /* high-mid, presence, brilliance, air */\n"
    "uniform float iHue;\n"
    "out vec4 nv_FragColor;\n"
    "#line 1\n";
static const char *FS_TAIL =
    "\nvoid main(){ vec4 c = vec4(0.0); mainImage(c, gl_FragCoord.xy); nv_FragColor = vec4(c.rgb, 1.0); }\n";

static const char *FS_BLIT =
    "#version 300 es\nprecision mediump float; in vec2 uv; out vec4 o;\n"
    "uniform sampler2D tex; uniform float fade; uniform vec2 uvs;\n"
    "void main(){ o = vec4(texture(tex, uv * uvs).rgb * fade, 1.0); }\n";

/* menu tile: rounded panel + image + selection glow; dim = background dim pass */
static const char *FS_TILE =
    "#version 300 es\nprecision mediump float; in vec2 uv; out vec4 o;\n"
    "uniform sampler2D tex; uniform float sel; uniform float alpha; uniform vec2 px; uniform int mode;\n"
    "float rbox(vec2 p, vec2 b, float r){ vec2 q = abs(p)-b+r; return length(max(q,0.0))+min(max(q.x,q.y),0.0)-r; }\n"
    "void main(){\n"
    "  if (mode == 1) { o = vec4(0.0, 0.0, 0.0, 0.55*alpha); return; }\n"
    "  vec4 t = texture(tex, vec2(uv.x, 1.0-uv.y));\n"
    "  if (mode == 2) { o = vec4(t.rgb, t.a*alpha); return; }\n"
    "  vec2 p = (uv-0.5)*px; float d = rbox(p, px*0.5-vec2(10.0), 22.0);\n"
    "  float inside = 1.0 - smoothstep(-1.0, 1.0, d);\n"
    "  float ring = (1.0 - smoothstep(0.0, 3.0, abs(d+2.0))) * sel;\n"
    "  float glow = exp(-max(d,0.0)/9.0) * sel * (1.0-inside);\n"
    "  vec3 panel = mix(vec3(0.06,0.07,0.10), vec3(0.12,0.14,0.20), sel);\n"
    "  vec3 col = mix(panel, t.rgb, t.a);\n"
    "  vec3 accent = vec3(0.35, 0.75, 1.0);\n"
    "  col = col*inside + accent*ring;\n"
    "  float a = max(inside*0.92, max(ring, glow*0.8));\n"
    "  o = vec4(col + accent*glow*(1.0-inside), a*alpha);\n"
    "}\n";

static GLuint compile(GLenum type, const char *src, const char *what) {
    GLuint s = glCreateShader(type);
    glShaderSource(s, 1, &src, NULL);
    glCompileShader(s);
    GLint ok; glGetShaderiv(s, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[4096]; glGetShaderInfoLog(s, sizeof log, NULL, log);
        fprintf(stderr, "nexxvis: compile error in %s:\n%s\n", what, log);
        glDeleteShader(s); return 0;
    }
    return s;
}

static GLuint link_prog(const char *vs, const char *fs, const char *what) {
    GLuint v = compile(GL_VERTEX_SHADER, vs, what), f = compile(GL_FRAGMENT_SHADER, fs, what);
    if (!v || !f) { if (v) glDeleteShader(v); if (f) glDeleteShader(f); return 0; }
    GLuint p = glCreateProgram();
    glAttachShader(p, v); glAttachShader(p, f);
    glLinkProgram(p);
    glDeleteShader(v); glDeleteShader(f);
    GLint ok; glGetProgramiv(p, GL_LINK_STATUS, &ok);
    if (!ok) { char log[2048]; glGetProgramInfoLog(p, sizeof log, NULL, log); fprintf(stderr, "link %s: %s\n", what, log); glDeleteProgram(p); return 0; }
    return p;
}

static char *read_file(const char *path) {
    FILE *f = fopen(path, "rb"); if (!f) return NULL;
    fseek(f, 0, SEEK_END); long n = ftell(f); fseek(f, 0, SEEK_SET);
    char *b = malloc(n + 1); if (!b) { fclose(f); return NULL; }
    if (fread(b, 1, n, f) != (size_t)n) { free(b); fclose(f); return NULL; }
    b[n] = 0; fclose(f); return b;
}

typedef struct { char name[256]; GLuint prog; GLint uRes, uTime, uDt, uFrame, uCh0, uCh1, uCh2, uCh3, uCh4, uCh5, uCh6, uCh7, uCh8, uCh9, uLevel, uRect, uBeat, uBPM, uCoverA, uCoverB, uGenomeA, uGenomeB, uHue, uEntropy, uElements, uBandA, uBandB, uStory, uSO; float scale; } Viz;
static Viz g_viz[MAX_SHADERS];
static int g_nviz = 0;

static int cmpstr(const void *a, const void *b) { return strcmp((const char *)a, (const char *)b); }

static void load_shaders(const char *dir) {
    for (int i = 0; i < g_nviz; i++) glDeleteProgram(g_viz[i].prog);
    g_nviz = 0;
    char names[MAX_SHADERS][256]; int nn = 0;
    DIR *d = opendir(dir);
    if (!d) { fprintf(stderr, "nexxvis: cannot open %s\n", dir); return; }
    struct dirent *e;
    while ((e = readdir(d)) && nn < MAX_SHADERS) {
        size_t l = strlen(e->d_name);
        if (l > 5 && strcmp(e->d_name + l - 5, ".frag") == 0) snprintf(names[nn++], 256, "%s", e->d_name);
    }
    closedir(d);
    qsort(names, nn, 256, cmpstr);
    for (int i = 0; i < nn; i++) {
        char path[1280]; snprintf(path, sizeof path, "%.1000s/%.255s", dir, names[i]);
        char *body = read_file(path); if (!body) continue;
        size_t n = strlen(FS_HEAD) + strlen(body) + strlen(FS_TAIL) + 1;
        char *src = malloc(n); snprintf(src, n, "%s%s%s", FS_HEAD, body, FS_TAIL);
        GLuint p = link_prog(VS, src, names[i]);
        /* optional per-shader render scale: "nv:scale=0.33" anywhere in the file */
        float sc = -1.0f;
        const char *tag = strstr(body, "nv:scale=");
        if (tag) sc = atof(tag + 9);
        free(body); free(src);
        if (!p) continue;
        Viz *v = &g_viz[g_nviz++];
        snprintf(v->name, sizeof v->name, "%.255s", names[i]);
        v->prog = p;
        v->scale = sc;
        v->uRect = glGetUniformLocation(p, "rect");
        v->uRes = glGetUniformLocation(p, "iResolution"); v->uTime = glGetUniformLocation(p, "iTime");
        v->uDt = glGetUniformLocation(p, "iTimeDelta"); v->uFrame = glGetUniformLocation(p, "iFrame");
        v->uCh0 = glGetUniformLocation(p, "iChannel0"); v->uLevel = glGetUniformLocation(p, "iLevel");
        v->uCh1 = glGetUniformLocation(p, "iChannel1");
        v->uCh2 = glGetUniformLocation(p, "iChannel2");
        v->uCh3 = glGetUniformLocation(p, "iChannel3");
        v->uCh4 = glGetUniformLocation(p, "iChannel4");
        v->uCh5 = glGetUniformLocation(p, "iChannel5");
        v->uCh6 = glGetUniformLocation(p, "iChannel6");
        v->uCh7 = glGetUniformLocation(p, "iChannel7");
        v->uCh8 = glGetUniformLocation(p, "iChannel8");
        v->uCh9 = glGetUniformLocation(p, "iChannel9");
        v->uBeat = glGetUniformLocation(p, "iBeat"); v->uBPM = glGetUniformLocation(p, "iBPM");
        v->uCoverA = glGetUniformLocation(p, "iCoverA"); v->uCoverB = glGetUniformLocation(p, "iCoverB");
        v->uGenomeA = glGetUniformLocation(p, "iGenomeA"); v->uGenomeB = glGetUniformLocation(p, "iGenomeB");
        v->uHue = glGetUniformLocation(p, "iHue");
        v->uEntropy = glGetUniformLocation(p, "iEntropy");
        v->uStory = glGetUniformLocation(p, "iStory");
        v->uSO = glGetUniformLocation(p, "iSO");
        v->uElements = glGetUniformLocation(p, "iElements");
        v->uBandA = glGetUniformLocation(p, "iBandA");
        v->uBandB = glGetUniformLocation(p, "iBandB");
        fprintf(stderr, "nexxvis: loaded %s\n", names[i]);
    }
}

typedef struct { GLuint tex; int w, h; } Img;

static int load_rgba(const char *path, Img *img) {
    FILE *f = fopen(path, "rb"); if (!f) return -1;
    uint32_t wh[2];
    if (fread(wh, 4, 2, f) != 2 || wh[0] == 0 || wh[1] == 0 || wh[0] > 4096 || wh[1] > 4096) { fclose(f); return -1; }
    size_t n = (size_t)wh[0] * wh[1] * 4;
    unsigned char *px = malloc(n);
    if (!px || fread(px, 1, n, f) != n) { free(px); fclose(f); return -1; }
    fclose(f);
    glGenTextures(1, &img->tex);
    glBindTexture(GL_TEXTURE_2D, img->tex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, wh[0], wh[1], 0, GL_RGBA, GL_UNSIGNED_BYTE, px);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    free(px);
    img->w = wh[0]; img->h = wh[1];
    return 0;
}

/* menu state from the hub: "<visible> <selected>" */
static void read_menu(const char *path, int *visible, int *sel) {
    static struct timespec last_mtime; static int v = 0, s = 0;
    struct stat st;
    if (stat(path, &st) == 0) {
        if (st.st_mtim.tv_sec != last_mtime.tv_sec || st.st_mtim.tv_nsec != last_mtime.tv_nsec) {
            last_mtime = st.st_mtim;
            FILE *f = fopen(path, "r");
            if (f) { int a = 0, b = 0; if (fscanf(f, "%d %d", &a, &b) == 2) { v = a; s = b; } fclose(f); }
        }
    } else { v = 0; }
    *visible = v; *sel = s;
}

/* now-playing card from the hub (raw RGBA, rendered for a 2560-wide screen). Returns 1 while a card
 * exists; reloads the texture when the file changes. */
static int poll_nowplaying(const char *path, Img *img) {
    static struct timespec last_mtime;
    static int have = 0;
    struct stat st;
    if (stat(path, &st) != 0) { have = 0; return 0; }
    if (st.st_mtim.tv_sec != last_mtime.tv_sec || st.st_mtim.tv_nsec != last_mtime.tv_nsec) {
        last_mtime = st.st_mtim;
        Img n = {0};
        if (load_rgba(path, &n) == 0) {
            if (img->tex) glDeleteTextures(1, &img->tex);
            *img = n;
            have = 1;
        }
    }
    return have && img->tex;
}

/* one line of /run/nexxbeat/beat (atomic replace on the writer side) */
static int read_beat_file(const char *path, BeatState *bs) {
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    char line[256];
    char *r = fgets(line, sizeof line, f);
    fclose(f);
    return r && beatstate_parse(line, bs);
}

/* CDJ card: like the now-playing card, but the file's mtime is a heartbeat
 * (< 5 s) written by nexxbeatd, so a stale/killed daemon's card disappears. */
static int poll_card(const char *path, Img *img, double now_epoch, double max_age) {
    static struct timespec last_mtime;
    static int have = 0;
    struct stat st;
    if (stat(path, &st) != 0) { have = 0; return 0; }
    double age = now_epoch - (st.st_mtim.tv_sec + st.st_mtim.tv_nsec * 1e-9);
    if (age > max_age) { have = 0; return 0; }
    if (st.st_mtim.tv_sec != last_mtime.tv_sec || st.st_mtim.tv_nsec != last_mtime.tv_nsec) {
        last_mtime = st.st_mtim;
        Img n = {0};
        if (load_rgba(path, &n) == 0) {
            if (img->tex) glDeleteTextures(1, &img->tex);
            *img = n;
            have = 1;
        }
    }
    return have && img->tex;
}

/* six 0..255 values: bar RGB, peak RGB */
static int read_palette(const char *path, float a[3], float b[3]) {
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    int r1, g1, b1, r2, g2, b2;
    int n = fscanf(f, "%d %d %d %d %d %d", &r1, &g1, &b1, &r2, &g2, &b2);
    fclose(f);
    if (n != 6) return 0;
    a[0] = r1 / 255.0f; a[1] = g1 / 255.0f; a[2] = b1 / 255.0f;
    b[0] = r2 / 255.0f; b[1] = g2 / 255.0f; b[2] = b2 / 255.0f;
    return 1;
}

static void set_rect(GLint loc, float x, float y, float w, float h, int W, int H) {
    /* pixel rect (origin top-left) -> NDC rect for VS (origin bottom-left, p in 0..1) */
    glUniform4f(loc, x / W * 2.0f - 1.0f, 1.0f - (y + h) / H * 2.0f, w / W * 2.0f, h / H * 2.0f);
}

int main(void) {
    signal(SIGTERM, on_term); signal(SIGINT, on_term); signal(SIGHUP, on_hup); signal(SIGPIPE, SIG_IGN);
    const char *card = envs("NV_CARD", "/dev/dri/by-path/platform-gpu-card");
    const char *conn = envs("NV_CONNECTOR", "HDMI-A-2");
    const char *mode = envs("NV_MODE", "1920x1080@60");
    const char *shdir = envs("NV_SHADERS", "/usr/local/share/nexxvis/shaders");
    const char *sink = envs("NV_SINK", "speakereq2x2");
    const char *menuf = envs("NV_MENU_FILE", "/run/nexxhub/menu");
    const char *tiles = envs("NV_TILES", "/usr/local/share/nexxvis/tiles");
    const char *npfile = envs("NV_NP_FILE", "/run/nexxhub/nowplaying.rgba");
    const char *cdjfile = envs("NV_CDJ_CARD", "/run/nexxbeat/cdj.rgba");
    const char *beatf = envs("NV_BEAT_FILE", "/run/nexxbeat/beat");
    const char *cdjcolors = envs("NV_CDJ_COLORS", "/run/nexxbeat/palette");
    const char *covercolors = envs("NV_COVER_COLORS", "/run/nexxhub/cover.colors");
    const char *specfile = envs("NV_SPECTRUM_FILE", "/run/nexxbeat/spectrum");
    const char *genomefile = envs("NV_GENOME_FILE", "/run/nexxbeat/genome");
    const char *entropyfile = envs("NV_ENTROPY_FILE", "/run/nexxbeat/entropy");
    const char *storyfile = envs("NV_STORY_FILE", "/run/nexxbeat/story");
    const char *trackkeyfile = envs("NV_TRACK_KEY", "/run/nexxhub/trackkey");
    const char *shaderfile = envs("NV_SHADER_FILE", "/var/lib/nexxhub/visualizer");
    double beat_offset = atof(envs("NV_BEAT_OFFSET_MS", "0")) / 1000.0;
    int beatlog = atoi(envs("NV_BEAT_LOG", "0"));
    int elemlog = atoi(envs("NV_ELEM_LOG", "0"));
    const char *snapfile = getenv("NV_SNAPSHOT");  /* dev: one-shot PPM capture */
    float scale = atof(envs("NV_SCALE", "0.5"));
    double cycle = atof(envs("NV_CYCLE", "300"));
    int fpslog = atoi(envs("NV_FPS_LOG", "0"));
    if (scale < 0.2f || scale > 1.0f) scale = 0.5f;
    int mw = 1920, mh = 1080, mhz = 60;
    sscanf(mode, "%dx%d@%d", &mw, &mh, &mhz);

    /* keep the text console from drawing over us */
    int tty_graphics = isatty(STDIN_FILENO) && ioctl(STDIN_FILENO, KDSETMODE, KD_GRAPHICS) == 0;

    Kms K;
    if (kms_init(&K, card, conn, mw, mh, mhz)) {
        /* fall back to any connected output */
        if (kms_init(&K, card, "", mw, mh, mhz)) return 1;
    }
    const int W = K.mode.hdisplay, H = K.mode.vdisplay;
    const int RW = (int)(W * scale), RH = (int)(H * scale);

    pthread_t at; pthread_create(&at, NULL, audio_thread, (void *)sink);

    /* geometry */
    GLuint vao, vbo;
    const float quad[] = {0, 0, 1, 0, 0, 1, 1, 1};
    glGenVertexArrays(1, &vao); glBindVertexArray(vao);
    glGenBuffers(1, &vbo); glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(GL_ARRAY_BUFFER, sizeof quad, quad, GL_STATIC_DRAW);
    glEnableVertexAttribArray(0); glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, 0);

    /* offscreen target at reduced resolution */
    GLuint fbo, ftex;
    glGenTextures(1, &ftex); glBindTexture(GL_TEXTURE_2D, ftex);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, RW, RH, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glGenFramebuffers(1, &fbo); glBindFramebuffer(GL_FRAMEBUFFER, fbo);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, ftex, 0);

    /* audio texture 512x2, R8 */
    GLuint atex; glGenTextures(1, &atex); glBindTexture(GL_TEXTURE_2D, atex);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_R8, BINS, 2, 0, GL_RED, GL_UNSIGNED_BYTE, NULL);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 4);

    /* straw backdrop baked once: the field is a static function of q */
    GLuint strawtex = make_straw(1024);
    GLuint swirltex = make_swirl(1024);
    GLuint sealtex = bake_art(1024, 0);
    GLuint penttex = bake_art(1024, 1);
    GLuint vorttex = bake_art(1024, 2);
    bake_dyn(13);

    GLuint blit = link_prog(VS, FS_BLIT, "blit");
    GLuint tilep = link_prog(VS, FS_TILE, "tile");
    if (!blit || !tilep) return 1;
    GLint bRect = glGetUniformLocation(blit, "rect"), bTex = glGetUniformLocation(blit, "tex"), bFade = glGetUniformLocation(blit, "fade"),
          bUvs = glGetUniformLocation(blit, "uvs");
    GLint tRect = glGetUniformLocation(tilep, "rect"), tTex = glGetUniformLocation(tilep, "tex"), tSel = glGetUniformLocation(tilep, "sel"),
          tAlpha = glGetUniformLocation(tilep, "alpha"), tPx = glGetUniformLocation(tilep, "px"), tMode = glGetUniformLocation(tilep, "mode");

    Img tile[MAX_TILES]; int ntiles = 0; Img hint = {0};
    for (int i = 0; i < MAX_TILES; i++) {
        char p[1024]; snprintf(p, sizeof p, "%s/tile%d.rgba", tiles, i);
        if (load_rgba(p, &tile[ntiles]) == 0) ntiles++; else break;
    }
    { char p[1024]; snprintf(p, sizeof p, "%s/hint.rgba", tiles); load_rgba(p, &hint); }
    fprintf(stderr, "nexxvis: %d menu tiles\n", ntiles);

    load_shaders(shdir);
    Analysis A; analysis_init(&A);
    BeatDetector bd; bd_init(&bd, now_s());
    unsigned char texbuf[BINS * 2];

    int cur = 0, frame = 0;
    double t0 = now_s(), tprev = t0, shader_start = t0, fade = 0.0, menu_a = 0.0, fps_t = t0; int fps_n = 0;
    Img np = {0}; double np_a = 0.0, np_check = 0.0; int np_have = 0;
    Img cdj = {0}; double cdj_a = 0.0, cdj_check = 0.0; int cdj_have = 0, cdj_was = 0;
    int switching = 0;
    int snapped = 0;
    float coverA[3] = {0.0f, 0.67f, 1.0f}, coverB[3] = {1.0f, 0.0f, 0.67f};
    double palette_check = 0.0;
    float genome[8] = {420.0f, 6.0f, 0.66f, 0.90f, 1.35f, 1.10f, 0.82f, 0.35f};
    float genome_target[8] = {420.0f, 6.0f, 0.66f, 0.90f, 1.35f, 1.10f, 0.82f, 0.35f};
    float entropy[4] = {0.5f, 0.5f, 0.5f, 0.5f};
    float entropy_target[4] = {0.5f, 0.5f, 0.5f, 0.5f};
    float story[4] = {1.0f, 0.0f, 0.0f, 0.0f};
    int story_target = 13, last_dyn = 13;
    double genome_check = 0.0, spec_check = 0.0, entropy_check = 0.0,
           elem_check = 0.0, story_check = 0.0;
    float hue = 0.0f; double hue_index = 0.0;
    int last_dj_track = 0; int have_cover = 0;
    float lastCA[3] = {0}, lastCB[3] = {0};
    char last_trackkey[256] = "";
    char pinned[256] = ""; int pinned_idx = -1; double shader_check = 0.0;
    static unsigned char specbuf[36];
    float sel_anim[MAX_TILES] = {0};
    double beat_log_t = 0.0;

    while (!g_quit) {
        if (g_reload) { g_reload = 0; load_shaders(shdir); cur = 0; shader_start = now_s(); pinned[0] = 0; pinned_idx = -1; shader_check = 0; }
        double t = now_s(), dt = t - tprev; tprev = t;
        if (dt > 0.1) dt = 0.1;
        int audio_stale = analysis_update(&A, (float)dt);
        if (audio_stale) bd_set_stale(&bd);
        else bd_update(&bd, A.mag, BD_MAX_BINS, t);

        for (int i = 0; i < BINS; i++) {
            texbuf[i] = (unsigned char)(A.spec[i] * 255.0f);
            texbuf[BINS + i] = (unsigned char)(A.wave[i] * 255.0f);
        }
        glBindTexture(GL_TEXTURE_2D, atex);
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
        glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, BINS, 2, GL_RED, GL_UNSIGNED_BYTE, texbuf);
        glPixelStorei(GL_UNPACK_ALIGNMENT, 4);

        /* beat source: Pro DJ Link wins while its state is fresh and playing.
         * The PipeWire onset detector (audio) is added in a later step. */
        BeatState bs;
        double beat_pulse = 0.0, beat_phase = 0.0, beat_bpm = 0.0, beat_conf = 0.0;
        int beat_source = 0, dj_track = 0;
        if (read_beat_file(beatf, &bs) && beatstate_live(&bs, t, 1.0)
                && bs.source == 2 && bs.playing) {
            double ph = beatstate_phase(&bs, t - beat_offset);
            /* Evaluate the pulse on the phase grid, not on the frame that
               notices the wrap.  A slow frame then shows the true decay
               instead of restarting a beat that happened up to a frame
               earlier.  This matches bd_pulse() for the audio fallback. */
            double period = bs.bpm > 1.0 ? 60.0 / bs.bpm : 0.5;
            beat_pulse = exp(-ph * period / 0.12);
            beat_phase = ph;
            beat_bpm = bs.bpm;
            beat_conf = bs.confidence;
            beat_source = 2;
            dj_track = bs.track_id;
        } else {
            double ab = bd_bpm(&bd), ac = bd_confidence(&bd);
            if (ab > 0.0 && ac > 0.0) {
                beat_pulse = bd_pulse(&bd, t);
                beat_phase = bd_phase(&bd, t);
                beat_bpm = ab;
                beat_conf = ac;
                beat_source = 1;
            }
        }
        if (beatlog && t - beat_log_t >= 1.0) {
            fprintf(stderr, "nexxvis: beat: source=%d bpm=%.1f conf=%.2f\n",
                    beat_source, beat_bpm, beat_conf);
            beat_log_t = t;
        }

        /* palette: the DJ card's art wins while that card is live, else the
         * now-playing cover; defaults keep the original blue/magenta. */
        if (t >= palette_check) {
            float ca[3], cb[3];
            if (cdj_have && read_palette(cdjcolors, ca, cb)) {
                memcpy(coverA, ca, sizeof coverA);
                memcpy(coverB, cb, sizeof coverB);
            } else if (read_palette(covercolors, ca, cb)) {
                memcpy(coverA, ca, sizeof coverA);
                memcpy(coverB, cb, sizeof coverB);
            } else {
                coverA[0] = 0.0f; coverA[1] = 0.67f; coverA[2] = 1.0f;
                coverB[0] = 1.0f; coverB[1] = 0.0f; coverB[2] = 0.67f;
            }
            int hue_event = 0;
            if (have_cover &&
                (memcmp(coverA, lastCA, sizeof coverA) || memcmp(coverB, lastCB, sizeof coverB)))
                hue_event = 1;
            memcpy(lastCA, coverA, sizeof coverA);
            memcpy(lastCB, coverB, sizeof coverB);
            have_cover = 1;
            if (dj_track && dj_track != last_dj_track) {
                last_dj_track = dj_track;
                hue_event = 1;
            }
            /* track switches: title + MPRIS track id, published by nowplaying */
            char tk[256] = "";
            FILE *tf = fopen(trackkeyfile, "r");
            if (tf) {
                if (!fgets(tk, sizeof tk, tf)) tk[0] = 0;
                fclose(tf);
            }
            size_t tl = strlen(tk);
            while (tl > 0 && (tk[tl - 1] == '\n' || tk[tl - 1] == '\r')) tk[--tl] = 0;
            if (tk[0] && strcmp(tk, last_trackkey) != 0) {
                snprintf(last_trackkey, sizeof last_trackkey, "%s", tk);
                hue_event = 1;
            }
            if (hue_event) {
                hue_index += 0.61803398875;
                hue = (float)(2.0 * M_PI * fmod(hue_index, 1.0));
                fprintf(stderr, "nexxvis: hue %.2f\n", hue);
            }
            palette_check = t + 0.5;
        }

        /* audio features for the genetic algorithm (32 bands + 4 levels) */
        if (t >= spec_check) {
            for (int k = 0; k < 32; k++) {
                float sum = 0.0f;
                for (int j = 0; j < 16; j++) sum += A.spec[k * 16 + j];
                specbuf[k] = (unsigned char)(sum / 16.0f * 255.0f);
            }
            for (int k = 0; k < 4; k++) specbuf[32 + k] = (unsigned char)(A.level[k] * 255.0f);
            char tmp[512];
            snprintf(tmp, sizeof tmp, "%s.tmp", specfile);
            FILE *sf = fopen(tmp, "wb");
            if (sf) { fwrite(specbuf, 1, 36, sf); fclose(sf); rename(tmp, specfile); }
            spec_check = t + 0.1;
        }
        if (elemlog && t >= elem_check) {
            fprintf(stderr, "nexxvis: elem k %.2f s %.2f h %.2f v %.2f | bands %.2f %.2f %.2f %.2f %.2f %.2f %.2f %.2f\n",
                    A.elem[0], A.elem[1], A.elem[2], A.elem[3],
                    A.band8_level[0], A.band8_level[1], A.band8_level[2],
                    A.band8_level[3], A.band8_level[4], A.band8_level[5],
                    A.band8_level[6], A.band8_level[7]);
            elem_check = t + 1.0;
        }
        if (t >= genome_check) {
            FILE *gf = fopen(genomefile, "r");
            if (gf) {
                float v[8];
                if (fscanf(gf, "%f %f %f %f %f %f %f %f",
                           &v[0], &v[1], &v[2], &v[3], &v[4], &v[5], &v[6], &v[7]) == 8)
                    memcpy(genome_target, v, sizeof genome_target);
                fclose(gf);
            }
            genome_check = t + 0.5;
        }
        if (t >= entropy_check) {
            unsigned char eb[16];
            FILE *ef = fopen(entropyfile, "rb");
            if (ef) {
                if (fread(eb, 1, 16, ef) == 16) {
                    for (int k = 0; k < 4; k++)
                        entropy_target[k] = (eb[4*k] + eb[4*k+1] + eb[4*k+2] + eb[4*k+3])
                                            / (4.0f * 255.0f);
                }
                fclose(ef);
            }
            entropy_check = t + 0.5;
        }
        /* upload a finished async bake; the old sprites keep drawing until then */
        dyn_finish();

        if (t >= story_check) {
            FILE *sf = fopen(storyfile, "r");
            if (sf) {
                float v[4]; int tgt = 0;
                int got = fscanf(sf, "%f %f %f %f %d",
                                 &v[0], &v[1], &v[2], &v[3], &tgt);
                if (got >= 4) {
                    memcpy(story, v, sizeof story);
                    if (got >= 5) story_target = tgt;
                }
                fclose(sf);
            }
            if (story_target != last_dyn && !dyn_busy) {
                if (dyn_start(story_target)) last_dyn = story_target;
            }
            story_check = t + 0.1;
        }

        /* pinned shader from the HiFiBerry web selector; "auto" resumes the cycle */
        if (t >= shader_check) {
            char sel[256] = "";
            FILE *sf = fopen(shaderfile, "r");
            if (sf) { if (!fgets(sel, sizeof sel, sf)) sel[0] = 0; fclose(sf); }
            size_t sl = strlen(sel);
            while (sl > 0 && (sel[sl - 1] == '\n' || sel[sl - 1] == '\r')) sel[--sl] = 0;
            if (strcmp(sel, pinned) != 0) {
                snprintf(pinned, sizeof pinned, "%s", sel);
                pinned_idx = -1;
                if (pinned[0] && strcmp(pinned, "auto") != 0) {
                    for (int i = 0; i < g_nviz; i++) {
                        if (strcmp(g_viz[i].name, pinned) == 0) {
                            pinned_idx = i; cur = i; switching = 0; fade = 1.0;
                            shader_start = now_s();
                            fprintf(stderr, "nexxvis: shader pinned %s\n", pinned);
                            break;
                        }
                    }
                    if (pinned_idx < 0) fprintf(stderr, "nexxvis: shader not found %s\n", pinned);
                } else {
                    fprintf(stderr, "nexxvis: shader auto\n");
                }
            }
            shader_check = t + 0.5;
        }

        /* shader cycling with fade through black */
        if (g_nviz > 1 && cycle > 0 && !switching && pinned_idx < 0 && t - shader_start > cycle) switching = 1;
        if (switching) {
            fade -= dt / 1.2;
            if (fade <= 0) { fade = 0; cur = (cur + 1) % g_nviz; shader_start = t; switching = 0; }
        } else if (fade < 1.0) { fade += dt / 1.5; if (fade > 1) fade = 1; }

        /* glide genome/entropy changes so the visual stays fluid */
        float gk = (float)(1.0 - exp(-dt * 3.0));
        for (int k = 0; k < 8; k++) genome[k] += (genome_target[k] - genome[k]) * gk;
        float ek = (float)(1.0 - exp(-dt * 2.5));
        for (int k = 0; k < 4; k++) entropy[k] += (entropy_target[k] - entropy[k]) * ek;

        /* pass 1: visualizer into FBO (per-shader scale renders into a sub-rectangle) */
        int vw = RW, vh = RH;
        if (g_nviz > 0 && g_viz[cur].scale > 0.05f && g_viz[cur].scale < scale) {
            vw = (int)(W * g_viz[cur].scale); vh = (int)(H * g_viz[cur].scale);
        }
        glBindFramebuffer(GL_FRAMEBUFFER, fbo);
        glViewport(0, 0, vw, vh);
        glDisable(GL_BLEND);
        if (g_nviz > 0) {
            Viz *v = &g_viz[cur];
            glUseProgram(v->prog);
            glUniform4f(v->uRect, -1, -1, 2, 2);
            glUniform3f(v->uRes, (float)vw, (float)vh, 1.0f);
            glUniform1f(v->uTime, (float)(t - t0));
            glUniform1f(v->uDt, (float)dt);
            glUniform1i(v->uFrame, frame);
            glUniform4f(v->uLevel, A.level[0], A.level[1], A.level[2], A.level[3]);
            glUniform4f(v->uBeat, (float)beat_pulse, (float)beat_phase,
                        (float)beat_source, (float)beat_conf);
            glUniform1f(v->uBPM, (float)beat_bpm);
            glUniform3f(v->uCoverA, coverA[0], coverA[1], coverA[2]);
            glUniform3f(v->uCoverB, coverB[0], coverB[1], coverB[2]);
            glUniform4f(v->uGenomeA, genome[0], genome[1], genome[2], genome[3]);
            glUniform4f(v->uGenomeB, genome[4], genome[5], genome[6], genome[7]);
            glUniform1f(v->uHue, hue);
            glUniform4f(v->uEntropy, entropy[0], entropy[1], entropy[2], entropy[3]);
            glUniform4f(v->uStory, story[0], story[1], story[2], story[3]);
            /* SO(nd) group element, once per frame: the visible-plane
               rotation and the anisotropic shadow of the higher planes.
               Computed here so the shader needs only a 2x2 multiply. */
            float ndv = story[0] >= 0.5f ? story[0] : 1.0f;
            if (ndv < 1.0f) ndv = 1.0f;
            if (ndv > 97.0f) ndv = 97.0f;
            float so_t = (float)(t - t0);
            float so_a = -so_t * 0.25f;
            float so_c = cosf(so_a), so_s = sinf(so_a);
            float so_x = 1.0f, so_y = 1.0f;
            for (int k = 0; k < 11; k++) {
                float wk = ndv - 2.0f - (float)k;
                if (wk <= 0.002f) continue;
                if (wk > 1.0f) wk = 1.0f;
                float ak = 0.05f + 0.03f * (float)k
                         + 0.02f * sinf(so_t * 0.07f + (float)k);
                float bk = 0.06f + 0.03f * (float)k
                         + 0.02f * sinf(so_t * 0.05f + (float)k * 1.3f);
                so_x *= 1.0f + (cosf(ak) - 1.0f) * wk;
                so_y *= 1.0f + (cosf(bk) - 1.0f) * wk;
            }
            glUniform4f(v->uSO, so_c, so_s, so_x, so_y);
            glUniform4f(v->uElements, A.elem[0], A.elem[1], A.elem[2], A.elem[3]);
            glUniform4f(v->uBandA, A.band8_level[0], A.band8_level[1],
                        A.band8_level[2], A.band8_level[3]);
            glUniform4f(v->uBandB, A.band8_level[4], A.band8_level[5],
                        A.band8_level[6], A.band8_level[7]);
            glActiveTexture(GL_TEXTURE8); glBindTexture(GL_TEXTURE_2D, dyntex[3]);
            glUniform1i(v->uCh8, 8);
            glActiveTexture(GL_TEXTURE7); glBindTexture(GL_TEXTURE_2D, dyntex[2]);
            glUniform1i(v->uCh7, 7);
            glActiveTexture(GL_TEXTURE6); glBindTexture(GL_TEXTURE_2D, dyntex[1]);
            glUniform1i(v->uCh6, 6);
            glActiveTexture(GL_TEXTURE5); glBindTexture(GL_TEXTURE_2D, dyntex[0]);
            glUniform1i(v->uCh5, 5);
            glActiveTexture(GL_TEXTURE4); glBindTexture(GL_TEXTURE_2D, vorttex);
            glUniform1i(v->uCh4, 4);
            glActiveTexture(GL_TEXTURE3); glBindTexture(GL_TEXTURE_2D, penttex);
            glUniform1i(v->uCh3, 3);
            glActiveTexture(GL_TEXTURE9); glBindTexture(GL_TEXTURE_2D, swirltex);
            glUniform1i(v->uCh9, 9);
            glActiveTexture(GL_TEXTURE2); glBindTexture(GL_TEXTURE_2D, sealtex);
            glUniform1i(v->uCh2, 2);
            glActiveTexture(GL_TEXTURE1); glBindTexture(GL_TEXTURE_2D, strawtex);
            glUniform1i(v->uCh1, 1);
            glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, atex);
            glUniform1i(v->uCh0, 0);
            glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
        } else {
            glClearColor(0.02f, 0.02f, 0.04f, 1); glClear(GL_COLOR_BUFFER_BIT);
        }

        /* pass 2: upscale to screen */
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
        glViewport(0, 0, W, H);
        glUseProgram(blit);
        glUniform4f(bRect, -1, -1, 2, 2);
        glUniform1f(bFade, (float)(fade * fade * (3 - 2 * fade)));
        glUniform2f(bUvs, (float)vw / RW, (float)vh / RH);
        glActiveTexture(GL_TEXTURE0); glBindTexture(GL_TEXTURE_2D, ftex); glUniform1i(bTex, 0);
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);

        /* pass 3: now-playing card, bottom-left (hidden while the menu is up) */
        int mvis = 0, msel = 0;
        read_menu(menuf, &mvis, &msel);
        if (t >= np_check) { np_have = poll_nowplaying(npfile, &np); np_check = t + 0.5; }
        if (t >= cdj_check) { cdj_have = poll_card(cdjfile, &cdj, now_epoch(), 5.0); cdj_check = t + 0.5; }
        if (cdj_have != cdj_was) {
            fprintf(stderr, "nexxvis: CDJ card %s\n", cdj_have ? "shown" : "hidden");
            cdj_was = cdj_have;
        }
        np_a += ((np_have && !mvis && !cdj_have ? 1.0 : 0.0) - np_a) * (1.0 - exp(-dt / 0.6));
        cdj_a += ((cdj_have && !mvis ? 1.0 : 0.0) - cdj_a) * (1.0 - exp(-dt / 0.6));
        if (cdj_a > 0.01 && cdj.tex) {
            float k = W / 2560.0f, nw = cdj.w * k, nh = cdj.h * k;
            glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
            glUseProgram(tilep);
            glUniform1i(tMode, 2);
            glUniform1f(tAlpha, (float)cdj_a);
            glActiveTexture(GL_TEXTURE0); glUniform1i(tTex, 0);
            glBindTexture(GL_TEXTURE_2D, cdj.tex);
            set_rect(tRect, W * 0.035f, H - nh - H * 0.06f, nw, nh, W, H);
            glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
            glDisable(GL_BLEND);
        }
        if (!cdj_have && np_a > 0.01 && np.tex) {
            float k = W / 2560.0f, nw = np.w * k, nh = np.h * k;
            glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
            glUseProgram(tilep);
            glUniform1i(tMode, 2);
            glUniform1f(tAlpha, (float)np_a);
            glActiveTexture(GL_TEXTURE0); glUniform1i(tTex, 0);
            glBindTexture(GL_TEXTURE_2D, np.tex);
            set_rect(tRect, W * 0.035f, H - nh - H * 0.06f, nw, nh, W, H);
            glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
            glDisable(GL_BLEND);
        }

        /* pass 4: menu overlay */
        double target = mvis ? 1.0 : 0.0;
        menu_a += (target - menu_a) * (1.0 - exp(-dt / 0.12));
        if (menu_a > 0.01 && ntiles > 0) {
            glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
            glUseProgram(tilep);
            glUniform1f(tAlpha, (float)menu_a);
            glUniform1i(tMode, 1); set_rect(tRect, 0, 0, W, H, W, H);
            glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
            float tw = W * 0.19f, th = tw * 0.62f, gap = W * 0.025f;
            float total = ntiles * tw + (ntiles - 1) * gap, x0 = (W - total) / 2, y0 = H * 0.5f - th / 2;
            glActiveTexture(GL_TEXTURE0); glUniform1i(tTex, 0);
            for (int i = 0; i < ntiles; i++) {
                float s = (i == msel) ? 1.0f : 0.0f;
                sel_anim[i] += (s - sel_anim[i]) * (float)(1.0 - exp(-dt / 0.08));
                float k = 1.0f + 0.08f * sel_anim[i];
                float w = tw * k, h = th * k, x = x0 + i * (tw + gap) - (w - tw) / 2, y = y0 - (h - th) / 2;
                glUniform1i(tMode, 0);
                glUniform1f(tSel, sel_anim[i]);
                glUniform2f(tPx, w, h);
                glBindTexture(GL_TEXTURE_2D, tile[i].tex);
                set_rect(tRect, x, y, w, h, W, H);
                glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
            }
            if (hint.tex) {
                float hw = hint.w * (W / 1920.0f), hh = hint.h * (W / 1920.0f);
                glUniform1i(tMode, 2);
                glBindTexture(GL_TEXTURE_2D, hint.tex);
                set_rect(tRect, (W - hw) / 2, y0 + th + H * 0.08f, hw, hh, W, H);
                glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
            }
            glDisable(GL_BLEND);
        }

        /* dev-only: one shot of the real TV frame after the scene settles */
        if (snapfile && !snapped && frame >= 120) {
            unsigned char *px = malloc((size_t)W * H * 4);
            if (px) {
                glBindFramebuffer(GL_FRAMEBUFFER, 0);
                glReadPixels(0, 0, W, H, GL_RGBA, GL_UNSIGNED_BYTE, px);
                FILE *f = fopen(snapfile, "wb");
                if (f) {
                    fprintf(f, "P6\n%d %d\n255\n", W, H);
                    for (int y = H - 1; y >= 0; y--)
                        for (int x = 0; x < W; x++)
                            fwrite(px + ((size_t)y * W + x) * 4, 1, 3, f);
                    fclose(f);
                    fprintf(stderr, "nexxvis: snapshot %s\n", snapfile);
                }
                free(px);
                snapped = 1;
            }
        }

        if (kms_present(&K)) { fprintf(stderr, "nexxvis: present failed, exiting\n"); break; }
        frame++; fps_n++;
        if (fpslog && t - fps_t > 5) { fprintf(stderr, "nexxvis: %.1f fps (%s)\n", fps_n / (t - fps_t), g_nviz ? g_viz[cur].name : "-"); fps_t = t; fps_n = 0; }
    }

    g_quit = 1;
    if (tty_graphics) ioctl(STDIN_FILENO, KDSETMODE, KD_TEXT);
    /* pw-record exits on SIGPIPE/EOF when we go; don't wait for the thread */
    return 0;
}
