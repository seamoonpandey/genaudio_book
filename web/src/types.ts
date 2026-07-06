export type User = {
  email: string;
  plan: "free" | "pro";
  chapters_converted: number;
  payment_failed: boolean;
};

export type ChapterStatus = "none" | "queued" | "running" | "done" | "failed";

export type ChapterMeta = {
  id: number;
  idx: number;
  title: string;
  chars: number;
  status: ChapterStatus;
  progress: number;
  duration: number | null;
  error: string | null;
};

export type BookSummary = {
  id: string;
  title: string;
  author: string | null;
  status: string;
  created_at: number;
  chapters_total: number;
  chapters_done: number;
  duration: number;
};

export type BookDetail = Omit<BookSummary, "chapters_total" | "chapters_done" | "duration"> & {
  chapters: ChapterMeta[];
};

export type ChapterText = {
  idx: number;
  total: number;
  title: string;
  text: string;
  status: ChapterStatus;
  chapter_id: number;
};

export const FREE_LIMIT = 3;
