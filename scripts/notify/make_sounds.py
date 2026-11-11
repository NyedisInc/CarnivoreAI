#!/usr/bin/env python3
from __future__ import annotations

import math
import struct
import subprocess
import sys
import wave
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
RATE = 44100
TARGET_RMS = 0.11
PEAK_CEILING = 0.79
LEVEL_TRIM = {"alarm": 1.33}
ATTACK_S = 0.004
RELEASE_S = 0.025

BELL = ((1.0, 1.0, 1.0), (2.0, 0.30, 1.9), (3.0, 0.10, 2.8))
REED = ((1.0, 1.0, 0.0), (3.0, 0.22, 0.0), (5.0, 0.08, 0.0))

NOTES: Dict[str, List[Tuple[float, float, float, Sequence[Tuple[float, float, float]], float]]] = {
    "ask": [(0.00, 659.26, 0.45, BELL, 0.30), (0.15, 880.00, 0.60, BELL, 0.40)],
    "done": [(0.00, 523.25, 0.40, BELL, 0.26), (0.11, 659.26, 0.40, BELL, 0.26), (0.22, 783.99, 0.75, BELL, 0.50)],
    "alarm": [(0.00 + 0.19 * i, 880.0 if i % 2 == 0 else 659.26, 0.15, REED, 0.0) for i in range(6)],
    "soft": [(0.00, 739.99, 0.55, BELL, 0.36)],
}
NAMES: Tuple[str, ...] = tuple(NOTES)


def _note(freq: float, length: float, partials: Sequence[Tuple[float, float, float]], ring: float) -> List[float]:
    n = int(length * RATE)
    out: List[float] = []
    total = sum(a for _, a, _ in partials)
    for i in range(n):
        t = i / RATE
        s = 0.0
        for mult, amp, speed in partials:
            decay = math.exp(-t * speed * 6.0 / ring) if ring else 1.0
            s += amp * decay * math.sin(2 * math.pi * freq * mult * t)
        env = 1.0
        if t < ATTACK_S:
            env = 0.5 - 0.5 * math.cos(math.pi * t / ATTACK_S)
        left = length - t
        if left < RELEASE_S:
            env *= 0.5 - 0.5 * math.cos(math.pi * left / RELEASE_S)
        out.append(s / total * env)
    out[-1] = 0.0
    return out


def render(name: str) -> List[int]:
    notes = NOTES[name]
    length = max(start + dur for start, _, dur, _, _ in notes)
    buf = [0.0] * (int(length * RATE) + 1)
    for start, freq, dur, partials, ring in notes:
        base = int(start * RATE)
        for i, v in enumerate(_note(freq, dur, partials, ring)):
            buf[base + i] += v
    rms = math.sqrt(sum(v * v for v in buf) / len(buf))
    peak = max(abs(v) for v in buf)
    gain = min(TARGET_RMS * LEVEL_TRIM.get(name, 1.0) / rms, PEAK_CEILING / peak)
    return [int(round(v * gain * 32767)) for v in buf]


def wav_bytes(samples: Sequence[int]) -> bytes:
    import io
    bio = io.BytesIO()
    with wave.open(bio, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return bio.getvalue()


def stats(samples: Sequence[int]) -> Dict[str, float]:
    peak = max(abs(v) for v in samples) / 32767
    rms = math.sqrt(sum(v * v for v in samples) / len(samples)) / 32767
    step = max(abs(b - a) for a, b in zip(samples, samples[1:])) / 32767
    return {"peak_db": 20 * math.log10(peak), "rms_db": 20 * math.log10(rms), "seconds": len(samples) / RATE,
            "first": samples[0], "last": samples[-1], "max_step": step}


def paths(name: str) -> Dict[str, Path]:
    stem = f"carnivore-{name}"
    return {"wav": ROOT / "client/sounds" / f"{stem}.wav", "aiff": ROOT / "macOS/sounds" / f"{stem}.aiff",
            "caf": ROOT / "ios/Carnivore/Sounds" / f"{stem}.caf"}


def main(argv: Sequence[str]) -> int:
    check = "--check" in argv
    bad = 0
    for name in NAMES:
        out = paths(name)
        data = wav_bytes(render(name))
        if check:
            if not out["wav"].exists() or out["wav"].read_bytes() != data:
                print(f"drift: {out['wav']}")
                bad = 1
            continue
        for p in out.values():
            p.parent.mkdir(parents=True, exist_ok=True)
        out["wav"].write_bytes(data)
        for fmt, flags in (("aiff", ["-f", "AIFF", "-d", "BEI16"]), ("caf", ["-f", "caff", "-d", "LEI16"])):
            subprocess.run(["afconvert", *flags, str(out["wav"]), str(out[fmt])], check=True)
        s = stats(render(name))
        print(f"{name}: {s['seconds']:.2f}s peak {s['peak_db']:.1f} dBFS rms {s['rms_db']:.1f} dBFS max step {s['max_step']:.3f}")
    return bad


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
