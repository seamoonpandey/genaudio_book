export type Chapter = {
  title: string;
  text: string;
  status: "pending" | "loading" | "running" | "done" | "failed";
  progress: number;
  duration: number | null;
};
export type Book = { id: string; title: string; chapters: Chapter[] };

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open("genaudi", 1);
    req.onupgradeneeded = () => req.result.createObjectStore("books", { keyPath: "id" });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function tx<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const req = fn(db.transaction("books", mode).objectStore("books"));
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export const getBooks = () => tx<Book[]>("readonly", (s) => s.getAll());
export const putBook = (b: Book) => tx("readwrite", (s) => s.put(b)).then(() => {});

export async function saveAudio(name: string, blob: Blob): Promise<void> {
  const dir = await navigator.storage.getDirectory();
  const fh = await dir.getFileHandle(name, { create: true });
  const w = await fh.createWritable();
  await w.write(blob);
  await w.close();
}

export async function audioURL(name: string): Promise<string> {
  const dir = await navigator.storage.getDirectory();
  const fh = await dir.getFileHandle(name);
  return URL.createObjectURL(await fh.getFile());
}
