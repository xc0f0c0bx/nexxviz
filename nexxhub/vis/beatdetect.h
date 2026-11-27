#ifndef NEXXVIS_BEATDETECT_H
#define NEXXVIS_BEATDETECT_H

/* Spectral-flux onset + tempo/phase detector for the PipeWire fallback.
 * One update per analysis tick with the low FFT bins (48 kHz / 8192 FFT). */

#define BD_MAX_BINS 256
#define BD_FLUX_HIST 100
#define BD_MAX_ONSETS 64
#define BD_IOI_BINS 176
#define BD_IOI_MIN 0.30
#define BD_IOI_STEP 0.004

typedef struct BeatDetector {
    double t_init, t_last_frame, t_last_onset;
    int have_prev;
    float prev_log[BD_MAX_BINS];
    float flux_hist[BD_FLUX_HIST];
    int flux_n, flux_pos;
    double onset_t[BD_MAX_ONSETS];
    float onset_s[BD_MAX_ONSETS];
    int onset_n;
    double period;       /* smoothed beat period, 0 if unknown */
    double anchor;       /* a beat time used for the phase grid */
    double bpm;
    double confidence;
} BeatDetector;

void bd_init(BeatDetector *d, double t);
void bd_update(BeatDetector *d, const float *mag, int bins, double t);
void bd_set_stale(BeatDetector *d);
double bd_pulse(const BeatDetector *d, double t);
double bd_phase(const BeatDetector *d, double t);
double bd_bpm(const BeatDetector *d);
double bd_confidence(const BeatDetector *d);

#endif
