#include <math.h>
#include <stdio.h>
#include <string.h>

#include "beatstate.h"

static int fails = 0;

#define CHECK(cond) do { if (!(cond)) { \
    fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); fails++; } } while (0)

static int close_enough(double a, double b, double eps) { return fabs(a - b) <= eps; }

int main(void) {
    BeatState s;
    CHECK(beatstate_parse("2 1 176.07 0.4312 0.94 1 123456.789 1217\n", &s) == 1);
    CHECK(s.source == 2);
    CHECK(s.deck == 1);
    CHECK(close_enough(s.bpm, 176.07, 1e-6));
    CHECK(close_enough(s.phase, 0.4312, 1e-6));
    CHECK(close_enough(s.confidence, 0.94, 1e-6));
    CHECK(s.playing == 1);
    CHECK(close_enough(s.write_mono, 123456.789, 1e-6));
    CHECK(s.track_id == 1217);

    CHECK(beatstate_live(&s, 123457.0, 1.0) == 1);
    CHECK(beatstate_live(&s, 123458.0, 1.0) == 0);

    double ph = beatstate_phase(&s, 123456.789 + 0.1);
    double want = fmod(0.4312 + 0.1 * 176.07 / 60.0, 1.0);
    CHECK(close_enough(ph, want, 1e-3));
    /* phase advances at 2.9345 Hz -> after 0.5 s it is 0.4312+1.46725 = 0.89845 */
    CHECK(close_enough(beatstate_phase(&s, 123456.789 + 0.5), 0.89845, 1e-3));

    double nb = beatstate_next_beat(&s, 123456.789 + 0.1, 0.0);
    CHECK(nb > 123456.789 + 0.1);
    CHECK(close_enough(nb, 123456.889 + (1.0 - want) * 60.0 / 176.07, 1e-3));
    double nb_off = beatstate_next_beat(&s, 123456.789 + 0.1, 0.020);
    CHECK(close_enough(nb_off - nb, 0.020, 1e-6));

    BeatState idle;
    CHECK(beatstate_parse("0 0 0 0 0 0 123.456 0\n", &idle) == 1);
    CHECK(idle.source == 0 && idle.playing == 0 && idle.bpm == 0.0);
    CHECK(beatstate_phase(&idle, 999.0) == 0.0);
    CHECK(isinf(beatstate_next_beat(&idle, 999.0, 0.0)));

    CHECK(beatstate_parse("0 0", &s) == 0);
    CHECK(beatstate_parse("garbage here", &s) == 0);
    CHECK(beatstate_parse("", &s) == 0);

    if (fails == 0) {
        printf("ok\n");
        return 0;
    }
    fprintf(stderr, "%d check(s) failed\n", fails);
    return 1;
}
