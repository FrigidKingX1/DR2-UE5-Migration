"""audio_analyze: classify DR2 engine vs effect audio and build a listen set.

Reads every WAV in a directory, computes acoustic features with a numpy
STFT (no scipy/matplotlib needed), classifies each sound as an engine loop
(repetitive, narrow-band, longer, steady) or a one-shot effect, writes a
summary JSON + CSV, renders a spectrogram contact sheet PNG, and copies the
best engine candidates into a 'Listen_Here' folder the user can open and
just double-click.

Intended to make "listening" automatable: I cannot hear audio, so this
substitutes objective audio analysis + a play-anywhere folder.
"""

import csv
import json
import math
import os
import shutil
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw


def read_wav(path: str) -> np.ndarray:
    """Return mono float samples in [-1, 1]."""
    with wave.open(path, "rb") as w:
        nch = w.getnchannels()
        sw = w.getsampwidth()
        rate = w.getframerate()
        nframes = w.getnframes()
        raw = w.readframes(nframes)
    if sw == 2:
        audio = np.frombuffer(raw, dtype=np.int16)
    elif sw == 4:
        audio = np.frombuffer(raw, dtype=np.int32)
    elif sw == 1:
        audio = np.frombuffer(raw, dtype=np.uint8).astype(np.int16) - 128
    else:
        raise ValueError(f"unsupported sample width {sw}")
    if nch > 1:
        audio = audio.reshape(-1, nch).mean(axis=1)
    return audio.astype(np.float32) / 32768.0, rate


def stft(sig: np.ndarray, rate: int, win=2048, hop=512):
    """Magnitude spectrogram (log) + frequency axis, via numpy framing."""
    if len(sig) < win:
        pad = win - len(sig)
        sig = np.concatenate([sig, np.zeros(pad, dtype=sig.dtype)])
    win_arr = np.hanning(win)
    n_frames = 1 + (len(sig) - win) // hop
    frames = np.stack(
        [sig[i * hop:i * hop + win] * win_arr for i in range(n_frames)])
    spec = np.abs(np.fft.rfft(frames, axis=1))
    log = np.log10(spec + 1e-6)
    freqs = np.fft.rfftfreq(win, 1.0 / rate)
    return log, freqs


def features(path: str) -> dict:
    sig, rate = read_wav(path)
    duration = len(sig) / rate
    rms = float(np.sqrt(np.mean(sig ** 2))) if len(sig) else 0.0
    spec, freqs = stft(sig, rate)
    # spectral centroid (energy-weighted frequency)
    power = np.sum(10.0 ** spec, axis=0)
    psum = power.sum()
    centroid = float(np.sum(freqs * power) / psum) if psum > 0 else 0.0
    # spectral flatness (geometric/arithmetic mean of power)
    flat = float(np.exp(np.mean(np.log(power + 1e-12))) /
                 (np.mean(power) + 1e-12)) if power.size else 0.0
    # envelope steady-ness: tiling RMS over 16 chunks, low coefficient
    n = max(1, len(sig) // 16)
    chunks = [np.sqrt(np.mean(sig[i * n:(i + 1) * n] ** 2))
              for i in range(16)]
    cv = float(np.std(chunks) / (np.mean(chunks) + 1e-9))
    return {
        "file": os.path.basename(path),
        "duration_s": round(duration, 3),
        "rms": round(rms, 5),
        "centroid_hz": round(centroid, 1),
        "flatness": round(flat, 5),
        "envelope_cv": round(cv, 4),
        "spec": spec, "freqs": freqs,
    }


def classify(f: dict) -> str:
    """Engine loops: long and steady (low envelope CV); real engine loops
    here are broadband-ish (flatness ~0.11-0.15) but very steady pitch."""
    if f["duration_s"] >= 2.5 and f["envelope_cv"] < 0.45:
        return "engine"
    if f["duration_s"] >= 0.5 and f["envelope_cv"] < 0.9:
        return "sustain"
    return "one_shot"


def render_spec(spec, freqs, width=512, height=256, max_hz=8000.0):
    """Render a single spectrogram to a grayscale PIL image."""
    spec = np.maximum(spec, -4.0)
    spec = (spec + 4.0) / 4.0
    # trim to max_hz
    n_bins = int((len(freqs) - 1) * max_hz / freqs[-1]) + 1
    spec = spec[:, :n_bins]
    img_arr = (np.clip(spec, 0, 1) * 255).astype(np.uint8)
    img = Image.fromarray(img_arr, mode="L").resize((width, height),
                                                     Image.BILINEAR)
    return img


def build_contact_sheet(rows, out_path, cols=5, thumb_w=512, thumb_h=256):
    """rows: list of (label, PIL image)."""
    n = len(rows)
    if n == 0:
        return
    c = cols
    r = math.ceil(n / c)
    label_h = 40
    gap = 8
    W = c * thumb_w + (c + 1) * gap
    H = r * (thumb_h + label_h) + (r + 1) * gap
    sheet = Image.new("RGB", (W, H), (20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    for idx, (label, img) in enumerate(rows):
        row, col = divmod(idx, c)
        x = gap + col * (thumb_w + gap)
        y = gap + row * (thumb_h + label_h + gap)
        sheet.paste(img, (x, y))
        draw.text((x + 4, y + thumb_h + 12), label, fill=(230, 230, 230))
    sheet.save(out_path)
    return out_path


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    wav_dir = argv[0]
    out_dir = argv[1] if len(argv) > 1 else os.path.join(wav_dir, "analysis")
    listen_dir = argv[2] if len(argv) > 2 else os.path.join(wav_dir,
                                                             "Listen_Here")
    top_n = int(argv[3]) if len(argv) > 3 else 6
    os.makedirs(out_dir, exist_ok=True)

    wavs = sorted(
        f for f in os.listdir(wav_dir) if f.lower().endswith(".wav"))
    parsed, rows = [], []
    for w in wavs:
        full = os.path.join(wav_dir, w)
        try:
            f = features(full)
            f["class"] = classify(f)
            parsed.append({k: v for k, v in f.items() if k not in ("spec", "freqs")})
            img = render_spec(f["spec"], f["freqs"])
            rows.append((f"{w} [{f['class']}] {f['duration_s']:.1f}s", img))
        except Exception as e:
            rows.append((f"{w} ERR", Image.new("L", (512, 256), 60)))
            parsed.append({"file": w, "error": str(e), "class": "error"})

    contact = os.path.join(out_dir, "spectrogram_contact_sheet.png")
    build_contact_sheet(rows, contact)

    with open(os.path.join(out_dir, "audio_report.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"count": len(parsed),
                   "contact_sheet": contact,
                   "sounds": parsed}, fh, indent=2)
    with open(os.path.join(out_dir, "audio_report.csv"), "w", newline="",
              encoding="utf-8") as fh:
        fieldnames = ["file", "class", "duration_s", "rms",
                      "centroid_hz", "flatness", "envelope_cv"]
        wr = csv.DictWriter(fh, fieldnames=fieldnames)
        wr.writeheader()
        for p in parsed:
            wr.writerow({k: p.get(k, "") for k in fieldnames})

    # curate engine candidates
    engine = sorted((p for p in parsed if p.get("class") == "engine"),
                    key=lambda p: (-p.get("duration_s", 0), p.get("rms", 0)))
    picks = engine[:top_n] or [p for p in parsed if p.get("class") != "error"][:top_n]
    os.makedirs(listen_dir, exist_ok=True)
    copied = []
    for p in picks:
        dst = os.path.join(listen_dir, p["file"])
        shutil.copyfile(os.path.join(wav_dir, p["file"]), dst)
        copied.append(dst)

    print(json.dumps({
        "analyzed": len(parsed),
        "classes": {c: sum(1 for p in parsed if p.get("class") == c)
                    for c in {"engine", "sustain", "one_shot", "error"}},
        "contact_sheet": contact,
        "engine_candidates": [os.path.basename(p["file"]) for p in picks],
        "listen_folder": listen_dir,
    }, indent=2))


if __name__ == "__main__":
    main()
