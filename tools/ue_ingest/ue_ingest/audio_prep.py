"""Audio preparation: scan transcoded WAVs and emit an audio manifest."""

from __future__ import annotations

import json
import os
import wave


def wav_duration(path: str) -> float:
    try:
        with wave.open(path, "rb") as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except Exception:
        return 0.0


def build_audio_manifest(wav_dir: str, bank_name: str = "s_mech") -> dict:
    sounds = []
    for fn in sorted(os.listdir(wav_dir)):
        if not fn.lower().endswith(".wav"):
            continue
        path = os.path.join(wav_dir, fn)
        sounds.append({
            "name": fn[:-4],
            "file": os.path.abspath(path),
            "duration_s": round(wav_duration(path), 3),
            "bank": bank_name,
        })
    sounds.sort(key=lambda s: -s["duration_s"])
    for rank, s in enumerate(sounds):
        s["engine_candidate_rank"] = rank  # longest = engine-loop candidate
    return {
        "bank": bank_name,
        "count": len(sounds),
        "sounds": sounds,
    }


def write_audio_manifest(wav_dir: str, out_path: str,
                         bank_name: str = "s_mech") -> str:
    manifest = build_audio_manifest(wav_dir, bank_name)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)
    return out_path
