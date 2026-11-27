# Nexxvis for macOS

A standalone macOS app for the nexxxen crop-genesis visualizer. It renders
the same `15-crop-genesis.frag` as the Raspberry Pi, driven by the Mac's own
system audio, with no server and no Pi.

## Build and run

```sh
./build.sh                 # builds build/Nexxvis.app
open build/Nexxvis.app
```

`build.sh` compiles the Swift package in release mode, assembles the app
bundle, copies the shared shader into `Contents/Resources/shaders/`, and
ad-hoc signs the bundle. The bundle matters: the Screen Recording permission
is tied to the app's identity.

Full screen is `Ctrl Cmd F` (the View menu has the same item).

## Package as a DMG

```sh
./package.sh               # builds build/Nexxvis-<version>.dmg
```

The image holds `Nexxvis.app` and an `Applications` symlink for drag-install.
The bundle is ad-hoc signed; on another Mac, right-click the app and choose
Open the first time, or remove the quarantine attribute:

```sh
xattr -dr com.apple.quarantine /Applications/Nexxvis.app
```

## Audio

The app captures the Mac's system audio with ScreenCaptureKit. On first run
macOS asks for Screen Recording permission for Nexxvis; until it is granted,
the app falls back to the microphone. The window title shows which source is
live (`Nexxvis — system audio` or `Nexxvis — microphone`).

The analysis is the Pi's: a 2048-point FFT, 512 log-spaced bins, three broad
levels with slow AGC, eight perceptual bands with fast flux, and four
elements (kick, snare, hat, vocal), all ported to vDSP. Beats come from
spectral-flux onsets with an adaptive threshold.

## Rendering

OpenGL 4.1 core in an `NSOpenGLView`. The visualizer renders into a
`0.42×` FBO (`nv:scale=0.42` in the shader header) and is blitted up with
linear filtering, exactly like the Pi renderer. The textures are baked on
the CPU at startup and per dimension, ported line for line from the Pi:
straw, swirl, heptagram, pentagram, vortex, and the four rose/crown layers.
The chapter ladder (1..13, a step every 10 s) and the SO(n) shadow are
computed per frame in Swift.

## Verification without a window

```sh
.build/release/Nexxvis --snapshot out.png --time 129.5
```

renders one frame offscreen at the 0.42 scale and writes a PNG. `--width`
and `--height` set the virtual screen size (default 2560×1440).

## Differences from the Pi build

- The album-art palette is fixed (blue/magenta) and the genome is fixed at
  values that give the usual formation; there is no GA or cover art yet.
- The story is the shader's own 1..13 ladder, not the hub's prime chase.
- No now-playing card, no shader menu, no Pro DJ Link.

These are natural next steps if the app should become a full companion.
