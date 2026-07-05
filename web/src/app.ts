import { audioURL, Book, getBooks, putBook, saveAudio } from "./db";

const API = import.meta.env.VITE_API_BASE || "http://localhost:8000";
const $ = <T extends HTMLElement>(s: string) => document.querySelector(s) as T;
const esc = (s: string) =>
  s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));

let books: Book[] = [];
let worker: Worker | null = null;
let busy = false;
const queue: { bookId: string; idx: number }[] = [];

function track(name: string) {
  fetch(`${API}/api/event`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ name }),
  }).catch(() => {});
}

$("#device-note").textContent =
  "gpu" in navigator ? "" : "No WebGPU on this device — synthesis will be slower (WASM).";

($("#waitlist-form") as HTMLFormElement).onsubmit = async (e) => {
  e.preventDefault();
  const email = ($("#waitlist-email") as HTMLInputElement).value;
  const r = await fetch(`${API}/api/waitlist`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email }),
  });
  $("#msg").textContent = r.ok ? "You're on the list." : (await r.json()).detail;
};

($("#file") as HTMLInputElement).onchange = async (e) => {
  const f = (e.target as HTMLInputElement).files?.[0];
  if (!f) return;
  $("#msg").textContent = "extracting…";
  const fd = new FormData();
  fd.append("file", f);
  try {
    const r = await fetch(`${API}/api/extract`, { method: "POST", body: fd });
    if (!r.ok) throw new Error((await r.json()).detail);
    const data = await r.json();
    const book: Book = {
      id: `${Date.now()}`,
      title: data.title || f.name,
      chapters: data.chapters.map((c: { title: string; text: string }) => ({
        ...c, status: "pending", progress: 0, duration: null,
      })),
    };
    await putBook(book);
    books.push(book);
    $("#msg").textContent = "";
    render();
  } catch (err) {
    $("#msg").textContent = String(err instanceof Error ? err.message : err);
  }
};

function synth(bookId: string, idx: number) {
  queue.push({ bookId, idx });
  const b = books.find((x) => x.id === bookId)!;
  b.chapters[idx].status = "loading";
  void putBook(b);
  render();
  pump();
}

function pump() {
  if (busy) return;
  const job = queue.shift();
  if (!job) return;
  busy = true;
  const book = books.find((b) => b.id === job.bookId)!;
  const ch = book.chapters[job.idx];
  ch.status = "running";
  track("synth_start");
  if (!worker) worker = new Worker(new URL("./synth-worker.ts", import.meta.url), { type: "module" });
  worker.onmessage = async (e) => {
    const m = e.data;
    if (m.type === "progress") ch.progress = m.done / m.total;
    if (m.type === "done") {
      await saveAudio(`${book.id}-${job.idx}.mp3`, m.mp3);
      ch.status = "done";
      ch.duration = Math.round(m.duration);
      track("synth_done");
    }
    if (m.type === "error") {
      ch.status = "failed";
      $("#msg").textContent = m.message;
    }
    if (m.type === "done" || m.type === "error") {
      await putBook(book);
      busy = false;
      pump();
    }
    render();
  };
  worker.postMessage({ text: ch.text });
}

async function play(bookId: string, idx: number) {
  const p = $("#player") as HTMLAudioElement;
  p.hidden = false;
  p.src = await audioURL(`${bookId}-${idx}.mp3`);
  void p.play();
}

async function download(bookId: string, idx: number, title: string) {
  const a = document.createElement("a");
  a.href = await audioURL(`${bookId}-${idx}.mp3`);
  a.download = `${String(idx + 1).padStart(2, "0")}-${title.replace(/[^a-z0-9]+/gi, "-")}.mp3`;
  a.click();
}

function render() {
  $("#books").innerHTML = books
    .map(
      (b) => `
    <h2>${esc(b.title)} <button data-all="${b.id}">Convert all</button></h2>
    <table>${b.chapters
      .map((c, i) => {
        const st = c.status === "running" ? `running ${Math.round(c.progress * 100)}%`
          : c.status === "loading" ? "fetching voice model…" : c.status;
        const act =
          c.status === "done"
            ? `<button data-play="${b.id}:${i}">▶</button> <button data-dl="${b.id}:${i}">↓</button>`
            : c.status === "pending" || c.status === "failed"
              ? `<button data-synth="${b.id}:${i}">${c.status === "failed" ? "retry" : "convert"}</button>`
              : "";
        const mins = c.duration ? ` · ${Math.round(c.duration / 60)}m` : "";
        return `<tr><td title="${esc(c.title)}">${i + 1}. ${esc(c.title)}</td>
          <td>${Math.round(c.text.length / 1000)}k${mins}</td>
          <td class="status-${c.status}">${st}</td><td>${act}</td></tr>`;
      })
      .join("")}</table>`,
    )
    .join("");
  document.querySelectorAll<HTMLButtonElement>("[data-synth]").forEach((el) => {
    el.onclick = () => { const [id, i] = el.dataset.synth!.split(":"); synth(id, +i); };
  });
  document.querySelectorAll<HTMLButtonElement>("[data-play]").forEach((el) => {
    el.onclick = () => { const [id, i] = el.dataset.play!.split(":"); void play(id, +i); };
  });
  document.querySelectorAll<HTMLButtonElement>("[data-dl]").forEach((el) => {
    el.onclick = () => {
      const [id, i] = el.dataset.dl!.split(":");
      const b = books.find((x) => x.id === id)!;
      void download(id, +i, b.chapters[+i].title);
    };
  });
  document.querySelectorAll<HTMLButtonElement>("[data-all]").forEach((el) => {
    el.onclick = () => {
      const b = books.find((x) => x.id === el.dataset.all)!;
      b.chapters.forEach((c, i) => {
        if (c.status === "pending" || c.status === "failed") synth(b.id, i);
      });
    };
  });
}

getBooks().then((bs) => {
  // stale in-flight statuses from a closed tab -> pending
  books = bs.map((b) => ({
    ...b,
    chapters: b.chapters.map((c) =>
      c.status === "running" || c.status === "loading" ? { ...c, status: "pending" as const } : c,
    ),
  }));
  render();
});
