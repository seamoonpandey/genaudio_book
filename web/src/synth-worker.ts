import { KokoroTTS } from "kokoro-js";
import { Mp3Encoder } from "@breezystack/lamejs";
import { chunkSentences } from "./chunk";

const MODEL = "onnx-community/Kokoro-82M-v1.0-ONNX";
const VOICE = "af_heart";
const RATE = 24000;
const PAUSE = new Int16Array(RATE * 0.3); // beat between chunks

let tts: KokoroTTS | null = null;

function toInt16(f32: Float32Array): Int16Array {
  const out = new Int16Array(f32.length);
  for (let i = 0; i < f32.length; i++) {
    const s = Math.max(-1, Math.min(1, f32[i]));
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

self.onmessage = async (e: MessageEvent<{ text: string }>) => {
  try {
    if (!tts) {
      postMessage({ type: "loading" });
      const device = "gpu" in navigator ? "webgpu" : "wasm";
      tts = await KokoroTTS.from_pretrained(MODEL, { dtype: "q8", device });
    }
    const chunks = chunkSentences(e.data.text);
    const enc = new Mp3Encoder(1, RATE, 64);
    const parts: Uint8Array[] = [];
    let samples = 0;
    for (let i = 0; i < chunks.length; i++) {
      const audio = await tts.generate(chunks[i], { voice: VOICE });
      const pcm = toInt16(audio.audio as Float32Array);
      parts.push(enc.encodeBuffer(pcm), enc.encodeBuffer(PAUSE));
      samples += pcm.length + PAUSE.length;
      postMessage({ type: "progress", done: i + 1, total: chunks.length });
    }
    parts.push(enc.flush());
    postMessage({
      type: "done",
      mp3: new Blob(parts as BlobPart[], { type: "audio/mpeg" }),
      duration: samples / RATE,
    });
  } catch (err) {
    postMessage({ type: "error", message: String(err) });
  }
};
