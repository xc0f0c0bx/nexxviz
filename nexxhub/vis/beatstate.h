#ifndef NEXXVIS_BEATSTATE_H
#define NEXXVIS_BEATSTATE_H

/* One line of /run/nexxbeat/beat:
 *   <source> <deck> <bpm> <phase> <confidence> <playing> <write_mono> <track_id>
 * source: 0 idle, 1 audio (visualizer-only), 2 Pro DJ Link.
 * write_mono is CLOCK_MONOTONIC seconds; phase is the beat fraction at that time.
 */
typedef struct {
    int source, deck, playing, track_id;
    double bpm, phase, confidence, write_mono;
} BeatState;

int beatstate_parse(const char *line, BeatState *out);
int beatstate_live(const BeatState *s, double now, double max_age);
double beatstate_phase(const BeatState *s, double now);
double beatstate_next_beat(const BeatState *s, double now, double offset_s);

#endif
