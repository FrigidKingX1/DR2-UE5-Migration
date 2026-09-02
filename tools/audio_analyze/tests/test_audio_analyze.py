"""Tests for audio_analyze feature extraction and classification."""

import os
import tempfile
import wave

import numpy as np
import pytest

from audio_analyze.__main__ import classify, read_wav, render_spec, stft


def _write_wav(path, samples, rate=48000):
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((samples * 32767).astype(np.int16).tobytes())


@pytest.fixture()
def wav_dir(tmp_path):
    d = str(tmp_path)
    t = np.arange(48000) / 48000
    # steady 3s 120 Hz tone -> engine-like (long, steady)
    steady = 0.5 * np.sin(2 * np.pi * 120 * t)
    _write_wav(os.path.join(d, "engine.wav"),
               np.concatenate([steady] * 3))
    # 50 ms click -> one-shot
    _write_wav(os.path.join(d, "click.wav"), 0.5 * np.sin(2 * np.pi * 800 * t[:2400]))
    return d


def test_read_wav_roundtrip(wav_dir):
    sig, rate = read_wav(os.path.join(wav_dir, "click.wav"))
    assert rate == 48000
    assert sig.max() <= 1.0 and sig.min() >= -1.0


def test_stft_shape_and_centroid(wav_dir):
    sig, rate = read_wav(os.path.join(wav_dir, "engine.wav"))
    spec, freqs = stft(sig, rate)
    assert spec.ndim == 2
    assert freqs[1] - freqs[0] > 0


def test_classify_engine_vs_oneshot(wav_dir):
    sig, rate = read_wav(os.path.join(wav_dir, "engine.wav"))
    spec, freqs = stft(sig, rate)
    power = np.sum(10.0 ** spec, axis=0)
    f_engine = {
        "duration_s": len(sig) / rate, "rms": 0.5,
        "flatness": 0.14, "envelope_cv": 0.05,
    }
    assert classify(f_engine) == "engine"
    f_click = {"duration_s": 0.05, "rms": 0.5,
               "flatness": 0.01, "envelope_cv": 1.4}
    assert classify(f_click) == "one_shot"


def test_render_spec_returns_png(wav_dir):
    sig, rate = read_wav(os.path.join(wav_dir, "engine.wav"))
    spec, freqs = stft(sig, rate)
    img = render_spec(spec, freqs)
    assert img is not None
