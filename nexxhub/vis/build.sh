#!/bin/sh
set -eu
cd "$(dirname "$0")"
gcc -O2 -Wall -Wextra -I/usr/include/libdrm -o nexxvis nexxvis.c beatstate.c beatdetect.c \
    -lEGL -lGLESv2 -lgbm -ldrm -lm -lpthread
gcc -O2 -Wall -Wextra -o test_beatstate test_beatstate.c beatstate.c -lm
gcc -O2 -Wall -Wextra -o test_beatdetect test_beatdetect.c beatdetect.c -lm
