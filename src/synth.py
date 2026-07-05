"""Chapter text -> MP3 via kokoro-onnx + ffmpeg."""
import os
import re
import subprocess
import tempfile

import numpy as np
import soundfile as sf

MODEL = os.path.join(os.path.dirname(__file__), "..", "models", "kokoro-v1.0.onnx")
VOICES = os.path.join(os.path.dirname(__file__), "..", "models", "voices-v1.0.bin")
VOICE = "af_heart"
MAX_CHUNK = 400  # chars; kokoro degrades on very long inputs

_kokoro = None


def _engine():
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro
        _kokoro = Kokoro(MODEL, VOICES)
    return _kokoro


def chunk_sentences(text, max_chars=MAX_CHUNK):
    """Split on sentence ends, pack into <=max_chars chunks."""
    sentences = re.split(r"(?<=[.!?”\"])\s+", text)
    chunks, cur = [], ""
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        while len(s) > max_chars:  # pathological run-on: hard split
            chunks.append(s[:max_chars])
            s = s[max_chars:]
        if len(cur) + len(s) + 1 > max_chars and cur:
            chunks.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        chunks.append(cur)
    return chunks


def synth_chapter(text, out_mp3, progress=None):
    """Synthesize text to out_mp3. progress(done, total) optional callback."""
    k = _engine()
    chunks = chunk_sentences(text)
    waves, sr = [], 24000
    for i, c in enumerate(chunks):
        samples, sr = k.create(c, voice=VOICE, speed=1.0, lang="en-us")
        waves.append(samples)
        waves.append(np.zeros(int(sr * 0.3), dtype=samples.dtype))  # beat between chunks
        if progress:
            progress(i + 1, len(chunks))
    audio = np.concatenate(waves)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav = tmp.name
    try:
        sf.write(wav, audio, sr)
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-b:a", "64k", out_mp3],
            check=True,
        )
    finally:
        os.unlink(wav)
    return len(audio) / sr  # duration seconds


if __name__ == "__main__":
    # smoke: one sentence -> playable mp3
    dur = synth_chapter("The quick brown fox jumped over the lazy dog.", "/tmp/genaudi-smoke.mp3")
    assert dur > 1, dur
    print(f"ok {dur:.1f}s -> /tmp/genaudi-smoke.mp3")
