import type { BookDetail, BookSummary, ChapterText, User } from "./types";

export const API = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) {
    super(message);
  }
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = init.method || "GET";
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  if (method !== "GET") headers["X-Requested-With"] = "genaudi";
  if (init.body && typeof init.body === "string") headers["Content-Type"] = "application/json";
  const r = await fetch(`${API}${path}`, { ...init, method, headers, credentials: "include" });
  if (!r.ok) {
    let code = "error", message = `request failed (${r.status})`;
    try {
      const body = await r.json();
      code = body.error?.code ?? code;
      message = body.error?.message ?? message;
    } catch { /* non-JSON error body */ }
    throw new ApiError(code, message, r.status);
  }
  return r.json();
}

export const getMe = () => req<{ user: User | null }>("/auth/me");
export const logout = () => req("/auth/logout", { method: "POST" });
export const sendMagic = (email: string) =>
  req<{ ok: boolean; dev_token?: string }>("/auth/magic", {
    method: "POST", body: JSON.stringify({ email }),
  });
export const verifyMagic = (token: string) =>
  req<{ user: User }>("/auth/magic/verify", { method: "POST", body: JSON.stringify({ token }) });
export const googleLogin = (code: string, redirect_uri: string) =>
  req<{ user: User }>("/auth/google", {
    method: "POST", body: JSON.stringify({ code, redirect_uri }),
  });

export const listBooks = () => req<BookSummary[]>("/books");
export const getBook = (id: string) => req<BookDetail>(`/books/${id}`);
export const deleteBook = (id: string) => req(`/books/${id}`, { method: "DELETE" });
export const uploadBook = (file: File) => {
  const fd = new FormData();
  fd.append("file", file);
  return req<BookDetail>("/books", { method: "POST", body: fd });
};
export const getChapterText = (bookId: string, idx: number) =>
  req<ChapterText>(`/books/${bookId}/chapters/${idx}`);
export const convertChapter = (chapterId: number) =>
  req<{ queued: number }>(`/chapters/${chapterId}/convert`, { method: "POST" });
export const convertAll = (bookId: string) =>
  req<{ queued: number }>(`/books/${bookId}/convert-all`, { method: "POST" });

export async function audioUrl(chapterId: number): Promise<string> {
  const { url } = await req<{ url: string }>(`/chapters/${chapterId}/audio-url`);
  return url.startsWith("/") ? `${API}${url}` : url; // dev: /files/... lives on the API origin
}

export const checkout = () => req<{ url: string }>("/billing/checkout", { method: "POST" });
export const portal = () => req<{ url: string }>("/billing/portal", { method: "POST" });
