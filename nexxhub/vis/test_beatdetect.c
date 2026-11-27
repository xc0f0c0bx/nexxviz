#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#include "beatdetect.h"

static int fails = 0;
#define CHECK(cond) do { if (!(cond)) { \
    fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); fails++; } } while (0)

static void fill_silence(float *mag) {
    for (int k = 0; k < 41; k++) mag[k] = 0.0001f;
}

int main(void) {
    BeatDetector d;
    float mag[41];
    double t = 0.0;
    bd_init(&d, 0.0);

    /* 10 s of 120 BPM clicks: a 3-frame pulse every 0.5 s. */
    for (int i = 0; i < 600; i++) {
        t = i / 60.0;
        fill_silence(mag);
        double within = fmod(t, 0.5);
        if (within < 2.5 / 60.0) {
            for (int k = 0; k < 9; k++) mag[k] += 1.0f;
            for (int k = 9; k < 21; k++) mag[k] += 0.4f;
        }
        bd_update(&d, mag, 41, t);
    }
    double bpm = bd_bpm(&d), conf = bd_confidence(&d);
    printf("clicks: bpm=%.2f conf=%.2f phase=%.3f\n", bpm, conf, bd_phase(&d, t));
    CHECK(fabs(bpm - 120.0) <= 3.0);
    CHECK(conf > 0.5);
    double period = 60.0 / bpm;
    double pred = t + (1.0 - bd_phase(&d, t)) * period;
    double err = fabs(fmod(pred + 0.25, 0.5) - 0.25);
    printf("next-beat prediction error: %.1f ms\n", err * 1000.0);
    CHECK(err < 0.020);

    /* 2 s of silence: confidence 0, pulse decayed. */
    for (int i = 0; i < 120; i++) {
        t = 10.0 + i / 60.0;
        for (int k = 0; k < 41; k++) mag[k] = 0.0f;
        bd_update(&d, mag, 41, t);
    }
    CHECK(bd_confidence(&d) == 0.0);
    CHECK(bd_pulse(&d, t) < 0.05);

    /* Stale audio: confidence and pulse must drop immediately. */
    BeatDetector s;
    bd_init(&s, 0.0);
    for (int i = 0; i < 600; i++) {
        t = i / 60.0;
        fill_silence(mag);
        double within = fmod(t, 0.5);
        if (within < 2.5 / 60.0) {
            for (int k = 0; k < 9; k++) mag[k] += 1.0f;
            for (int k = 9; k < 21; k++) mag[k] += 0.4f;
        }
        bd_update(&s, mag, 41, t);
    }
    bd_set_stale(&s);
    CHECK(bd_confidence(&s) == 0.0);
    CHECK(bd_pulse(&s, t) < 0.05);
    CHECK(bd_bpm(&s) == 0.0);

    /* Random noise must not look like a beat. */
    BeatDetector n;
    bd_init(&n, 0.0);
    srand(1234);
    for (int i = 0; i < 600; i++) {
        t = i / 60.0;
        for (int k = 0; k < 41; k++) mag[k] = (float)rand() / RAND_MAX;
        bd_update(&n, mag, 41, t);
    }
    printf("noise: bpm=%.2f conf=%.2f\n", bd_bpm(&n), bd_confidence(&n));
    CHECK(bd_confidence(&n) < 0.3);

    if (fails == 0) { printf("ok\n"); return 0; }
    fprintf(stderr, "%d check(s) failed\n", fails);
    return 1;
}
