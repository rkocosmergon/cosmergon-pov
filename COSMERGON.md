# cosmergon-pov

Fork of [ozkl/doomgeneric](https://github.com/ozkl/doomgeneric), upstream commit
`e257a09527062bfb986b6e5e0780839b6cbd5b71` (2026-10-11). Remote `upstream` points there.
License: GPL-2.0 (see `LICENSE`, unchanged).

## What this fork adds

- `doomgeneric/doomgeneric_headless.c`: platform layer without window, sound or input.
  Virtual clock (deterministic, as fast as the CPU allows), frames written as PPM (P6).
- `doomgeneric/Makefile.headless`: build without SDL and sound, output `cosmergon-pov-headless`.
- `scripts/download-freedoom.sh`: pinned, SHA-256 checked Freedoom download.
- `tools/ppm2png.py`: PPM to PNG (standard library only).
- `tests/test_headless.sh`: smoke test.
- One upstream change: `doomgeneric/i_system.c` skips the zenity error dialog when
  `POV_NO_ERROR_DIALOG` is defined (set in `Makefile.headless`). The message still goes to stderr.

## Build and run

    bash scripts/download-freedoom.sh
    make -C doomgeneric -f Makefile.headless
    mkdir -p out
    POV_OUT=out POV_EVERY=35 POV_FRAMES=1400 \
      doomgeneric/cosmergon-pov-headless -iwad assets/freedoom/freedoom1.wad
    python3 tools/ppm2png.py out/frame-000035.ppm out/frame-000035.png

Environment: `POV_OUT` (required output directory), `POV_EVERY` (default 35), `POV_FRAMES` (default 700).

## Test

    bash tests/test_headless.sh

## Freedoom

Game data is [Freedoom](https://freedoom.github.io/) 0.13.0, licensed under the BSD 3-clause
license (`assets/freedoom/COPYING.txt` after download). The IWAD is not part of this repository.
No original Doom data is used.
