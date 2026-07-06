"""TTS engines. Interface: synthesize(text, voice, progress_cb) -> (mp3_bytes, duration_s).
kokoro now; premium engines (elevenlabs, openai) slot in here later."""
import sys
import tempfile
from pathlib import Path

# container: synth.py sits next to worker.py; repo: it lives in src/
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import synth  # noqa: E402


class KokoroEngine:
    def synthesize(self, text, voice, progress_cb):
        with tempfile.TemporaryDirectory() as d:
            out = str(Path(d) / "out.mp3")
            duration = synth.synth_chapter(text, out, progress=progress_cb)
            return Path(out).read_bytes(), duration


_ENGINES = {"kokoro": KokoroEngine()}


def get(name: str):
    return _ENGINES[name]
