#include "beatstate.h"

#include <math.h>
#include <stdio.h>

int beatstate_parse(const char *line, BeatState *out) {
    if (!line || !out) return 0;
    int source, deck, playing, track;
    double bpm, phase, conf, mono;
    int n = sscanf(line, "%d %d %lf %lf %lf %d %lf %d",
                   &source, &deck, &bpm, &phase, &conf, &playing, &mono, &track);
    if (n != 8) return 0;
    if (phase < 0.0) phase = 0.0;
    if (phase > 1.0) phase = 1.0;
    out->source = source;
    out->deck = deck;
    out->bpm = bpm;
    out->phase = phase;
    out->confidence = conf;
    out->playing = playing;
    out->write_mono = mono;
    out->track_id = track;
    return 1;
}

int beatstate_live(const BeatState *s, double now, double max_age) {
    return fabs(now - s->write_mono) <= max_age;
}

double beatstate_phase(const BeatState *s, double now) {
    if (s->bpm <= 0.0) return 0.0;
    double p = s->phase + (now - s->write_mono) * s->bpm / 60.0;
    p = fmod(p, 1.0);
    if (p < 0.0) p += 1.0;
    return p;
}

double beatstate_next_beat(const BeatState *s, double now, double offset_s) {
    if (s->bpm <= 0.0) return INFINITY;
    double ph = beatstate_phase(s, now);
    return now + (1.0 - ph) * 60.0 / s->bpm + offset_s;
}
