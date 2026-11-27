# nexxviz

The nexxxen beat-reactive visualizer, in two builds that share one shader:

- `nexxhub/` — the Raspberry Pi renderer and its hub. A KMS/GBM/EGL GLES3
  renderer (`vis/nexxvis.c`) with the GLSL shaders in `vis/shaders/`, the
  Python services in `hub/` (PipeWire beat capture, Pro DJ Link clock, album
  art palette, genetic algorithm, story controller, web selector), systemd
  units in `units/`, and the HiFiBerryOS package in `packaging/`.
- `macos/` — a standalone Swift/OpenGL 4.1 app that renders the same
  `15-crop-genesis.frag` from the Mac's system audio. See `macos/README.md`.
- `docs/` — the design, plan and the running change ledger.

The shader is the shared core: `nexxhub/vis/shaders/15-crop-genesis.frag` is
copied into the macOS app bundle at build time, so both builds draw the same
formation.

## Raspberry Pi

```sh
ssh nexxxen
cd ~/src/nexxhub
sh vis/build.sh                      # builds vis/nexxvis
sh packaging/build_deb.sh --install  # package, install, restart services
```

The visualizer reads `/run/nexxbeat/spectrum` and `/run/nexxbeat/story` and
renders to the HDMI TV through DRM. Services: `nexxbeatd`, `nexx-genome`,
`nexx-story`, `nexx-visualizer`, `nexxvisualizer-web`.

## macOS

```sh
cd macos
./build.sh      # build/Nexxvis.app
./package.sh    # build/Nexxvis-<version>.dmg
```

## History

`docs/superpowers/sdd-ledger-2026-11-22-nexxvis-beat-reactive.md` records every
change with its measurements — frame rates, capture names, and the rulings
behind them.
