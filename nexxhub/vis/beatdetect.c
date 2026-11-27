#include "beatdetect.h"

#include <math.h>
#include <string.h>

static void sortf(float *a, int n) {
    for (int i = 1; i < n; i++) {
        float v = a[i];
        int j = i - 1;
        while (j >= 0 && a[j] > v) { a[j + 1] = a[j]; j--; }
        a[j + 1] = v;
    }
}

void bd_init(BeatDetector *d, double t) {
    memset(d, 0, sizeof *d);
    d->t_init = t;
    d->t_last_frame = t;
    d->t_last_onset = -1e9;
}

static void push_flux(BeatDetector *d, float v) {
    d->flux_hist[d->flux_pos] = v;
    d->flux_pos = (d->flux_pos + 1) % BD_FLUX_HIST;
    if (d->flux_n < BD_FLUX_HIST) d->flux_n++;
}

static void prune_onsets(BeatDetector *d, double t) {
    int drop = 0;
    while (drop < d->onset_n && d->onset_t[drop] < t - 8.0) drop++;
    if (drop > 0) {
        memmove(d->onset_t, d->onset_t + drop, (d->onset_n - drop) * sizeof(double));
        memmove(d->onset_s, d->onset_s + drop, (d->onset_n - drop) * sizeof(float));
        d->onset_n -= drop;
    }
}

static void add_onset(BeatDetector *d, double t, float strength) {
    if (d->onset_n == BD_MAX_ONSETS) {
        memmove(d->onset_t, d->onset_t + 1, (BD_MAX_ONSETS - 1) * sizeof(double));
        memmove(d->onset_s, d->onset_s + 1, (BD_MAX_ONSETS - 1) * sizeof(float));
        d->onset_n--;
    }
    d->onset_t[d->onset_n] = t;
    d->onset_s[d->onset_n] = strength;
    d->onset_n++;
}

void bd_update(BeatDetector *d, const float *mag, int bins, double t) {
    if (bins > BD_MAX_BINS) bins = BD_MAX_BINS;
    if (bins < 2) return;
    double dt = t - d->t_last_frame;
    if (dt < 0.0) dt = 0.0;

    float logmag[BD_MAX_BINS];
    for (int k = 0; k < bins; k++)
        logmag[k] = logf(1.0f + (mag[k] > 0.0f ? mag[k] : 0.0f));

    float flux = 0.0f;
    if (d->have_prev) {
        for (int k = 1; k < bins; k++) {
            float df = logmag[k] - d->prev_log[k];
            if (df > 0.0f) flux += df;
        }
    }
    memcpy(d->prev_log, logmag, (size_t)bins * sizeof(float));
    d->have_prev = 1;
    /* The flux is a per-update difference.  Normalize it to a 70 ms frame
       so the fixed floor and the history mean the same at any update rate
       (14 Hz renderer or 50 Hz analysis thread). */
    if (dt > 0.001 && dt < 0.2) flux *= (float)(0.07 / dt);
    push_flux(d, flux);

    /* adaptive threshold: rolling median + 0.35 * MAD */
    float tmp[BD_FLUX_HIST];
    int n = d->flux_n;
    memcpy(tmp, d->flux_hist, (size_t)n * sizeof(float));
    sortf(tmp, n);
    float med = tmp[n / 2];
    for (int i = 0; i < n; i++) tmp[i] = fabsf(d->flux_hist[i] - med);
    sortf(tmp, n);
    float mad = tmp[n / 2];

    if (flux > med + 0.35f * mad && flux > 0.02f && t - d->t_last_onset > 0.12) {
        add_onset(d, t, flux);
        d->t_last_onset = t;
    }
    prune_onsets(d, t);

    /* inter-onset histogram over the stored 8 s window */
    float raw[BD_IOI_BINS];
    memset(raw, 0, sizeof raw);
    float ioi_vals[BD_MAX_ONSETS];
    int ioi_bin[BD_MAX_ONSETS];
    int nioi = 0;
    for (int i = 1; i < d->onset_n; i++) {
        float ioi = (float)(d->onset_t[i] - d->onset_t[i - 1]);
        if (ioi < BD_IOI_MIN || ioi > 1.0f) continue;
        int b = (int)((ioi - BD_IOI_MIN) / BD_IOI_STEP);
        if (b < 0) b = 0;
        if (b >= BD_IOI_BINS) b = BD_IOI_BINS - 1;
        raw[b] += 1.0f;
        ioi_vals[nioi] = ioi;
        ioi_bin[nioi] = b;
        nioi++;
    }

    float hist[BD_IOI_BINS];
    memset(hist, 0, sizeof hist);
    for (int b = 0; b < BD_IOI_BINS; b++) {
        if (raw[b] <= 0.0f) continue;
        hist[b] += raw[b];
        if (b > 0) hist[b - 1] += 0.5f * raw[b];
        if (b + 1 < BD_IOI_BINS) hist[b + 1] += 0.5f * raw[b];
    }
    int peak = -1;
    float peakv = 0.0f;
    for (int b = 0; b < BD_IOI_BINS; b++)
        if (hist[b] > peakv) { peakv = hist[b]; peak = b; }

    d->confidence = 0.0;
    if (nioi >= 3 && peak >= 0 && d->onset_n >= 3) {
        double sum = 0.0;
        int cnt = 0;
        for (int i = 0; i < nioi; i++) {
            int dlt = ioi_bin[i] - peak;
            if (dlt < 0) dlt = -dlt;
            if (dlt <= 1) { sum += ioi_vals[i]; cnt++; }
        }
        if (cnt > 0) {
            double detected = sum / cnt;
            if (d->period <= 0.0) d->period = detected;
            else {
                double alpha = dt / 4.0;
                if (alpha > 1.0) alpha = 1.0;
                d->period += (detected - d->period) * alpha;
            }
        }
        float frac = raw[peak] / (float)nioi;
        float countf = d->onset_n / 8.0f;
        if (countf > 1.0f) countf = 1.0f;
        d->confidence = frac * countf;

        /* anchor = earliest residual over the last 16 onsets */
        int start = d->onset_n > 16 ? d->onset_n - 16 : 0;
        if (d->period > 0.0 && d->onset_n > start) {
            double t0 = d->onset_t[start];
            double minr = 1e9;
            for (int i = start; i < d->onset_n; i++) {
                double k = floor((d->onset_t[i] - t0) / d->period + 0.5);
                double r = d->onset_t[i] - k * d->period;
                if (r < minr) minr = r;
            }
            d->anchor = minr;
        }
    }
    if (d->period > 0.0) d->bpm = 60.0 / d->period;
    else d->bpm = 0.0;

    /* silence: no onset for 1.5 s means no confident beat */
    if (t - d->t_last_onset > 1.5) d->confidence = 0.0;
    d->t_last_frame = t;
}

void bd_set_stale(BeatDetector *d) {
    d->confidence = 0.0;
    d->t_last_frame = -1e9;   /* makes bd_pulse's staleness guard fire */
}

double bd_confidence(const BeatDetector *d) {    if (d->onset_n < 3) return 0.0;
    return d->confidence;
}

double bd_bpm(const BeatDetector *d) {
    if (d->confidence <= 0.0 || d->period <= 0.0) return 0.0;
    return 60.0 / d->period;
}

double bd_phase(const BeatDetector *d, double t) {
    if (d->period <= 0.0 || d->confidence <= 0.0) return 0.0;
    double p = fmod(t - d->anchor, d->period);
    if (p < 0.0) p += d->period;
    return p / d->period;
}

double bd_pulse(const BeatDetector *d, double t) {
    if (d->period <= 0.0 || d->confidence <= 0.0) return 0.0;
    if (t - d->t_last_frame > 0.5) return 0.0;
    return exp(-bd_phase(d, t) * d->period / 0.12);
}
