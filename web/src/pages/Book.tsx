import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, audioUrl, convertAll, convertChapter, getBook } from "../api";
import { useMe } from "../App";
import { Cover } from "../components/Cover";
import { playBook, usePlayer } from "../player";
import { FREE_LIMIT, type ChapterMeta } from "../types";
import styles from "./Book.module.css";

const mins = (s: number | null) => (s ? `${Math.max(1, Math.round(s / 60))} min` : "");
const estMins = (chars: number) => `~${Math.max(1, Math.round(chars / 900))} min`;

function StatusChip({ c }: { c: ChapterMeta }) {
  if (c.status === "running")
    return <span className="chip chip-running">Converting {Math.round(c.progress * 100)}%</span>;
  if (c.status === "queued") return <span className="chip chip-running">Waiting</span>;
  if (c.status === "done") return <span className="chip chip-done">Ready</span>;
  if (c.status === "failed")
    return <span className="chip chip-failed" title={c.error ?? undefined}>Failed</span>;
  return null;
}

export function Book() {
  const { bookId = "" } = useParams();
  const qc = useQueryClient();
  const me = useMe().data?.user;
  const { dispatch } = usePlayer();
  const [err, setErr] = useState<string | null>(null);

  const { data: book } = useQuery({
    queryKey: ["book", bookId],
    queryFn: () => getBook(bookId),
    refetchInterval: (q) =>
      q.state.data?.chapters.some((c) => c.status === "queued" || c.status === "running")
        ? 2000
        : false,
  });

  const refresh = () => void qc.invalidateQueries({ queryKey: ["book", bookId] });
  const onErr = (e: unknown) => setErr(e instanceof ApiError ? e.message : "something went wrong");
  const one = useMutation({ mutationFn: convertChapter, onSuccess: refresh, onError: onErr });
  const all = useMutation({ mutationFn: () => convertAll(bookId), onSuccess: refresh, onError: onErr });

  if (!book) return null;
  const done = book.chapters.filter((c) => c.status === "done");
  const totalDur = done.reduce((a, c) => a + (c.duration ?? 0), 0);
  const convertible = book.chapters.filter((c) => c.status === "none" || c.status === "failed").length;
  const freeLeft = me?.plan === "free" ? Math.max(FREE_LIMIT - me.chapters_converted, 0) : null;

  const tracks = done.map((c) => ({
    chapterId: c.id, title: c.title, bookId: book.id, bookTitle: book.title,
  }));

  const download = async (c: ChapterMeta) => {
    const a = document.createElement("a");
    a.href = await audioUrl(c.id);
    a.download = `${String(c.idx + 1).padStart(2, "0")}-${c.title.replace(/[^a-z0-9]+/gi, "-")}.mp3`;
    a.click();
  };

  return (
    <div className="container">
      <div className={styles.head}>
        <Cover title={book.title} size="lg" />
        <div className={styles.meta}>
          <p className={styles.crumb}><Link to="/library">Library</Link> /</p>
          <h1>{book.title}</h1>
          <p className="muted num">
            {book.chapters.length} chapters
            {totalDur > 0 && ` · ${(totalDur / 3600).toFixed(1)} h of audio so far`}
          </p>
          <div className={styles.headActions}>
            {tracks.length > 0 && (
              <button className="btn" onClick={() => playBook(dispatch, tracks, tracks[0].chapterId)}>
                ▶ Play book
              </button>
            )}
            <button
              className="btn btn-primary"
              disabled={convertible === 0 || all.isPending}
              onClick={() => { setErr(null); all.mutate(); }}
            >
              Convert all ({convertible})
            </button>
            {freeLeft !== null && (
              <span className="muted num">{freeLeft} of {FREE_LIMIT} free conversions left</span>
            )}
          </div>
          {err && (
            <p className={styles.error} role="alert">
              {err} {me?.plan === "free" && <Link to="/account">Upgrade to Pro →</Link>}
            </p>
          )}
        </div>
      </div>

      <ol className={styles.list}>
        {book.chapters.map((c) => (
          <li key={c.id} className={styles.row}>
            <span className={`${styles.n} muted num`}>{c.idx + 1}</span>
            <div className={styles.rowTitle}>
              <span title={c.title}>{c.title}</span>
              <span className="muted num">
                {c.status === "done" ? mins(c.duration) : estMins(c.chars)}
              </span>
            </div>
            {c.status === "running" && (
              <div className={styles.rowProgress} aria-hidden="true">
                <span style={{ width: `${c.progress * 100}%` }} />
              </div>
            )}
            <StatusChip c={c} />
            <div className={styles.actions}>
              <Link className="btn btn-quiet btn-sm" to={`/books/${book.id}/read/${c.idx}`}>
                Read
              </Link>
              {(c.status === "none" || c.status === "failed") && (
                <button
                  className="btn btn-sm"
                  disabled={one.isPending}
                  onClick={() => { setErr(null); one.mutate(c.id); }}
                >
                  {c.status === "failed" ? "Retry" : "Convert"}
                </button>
              )}
              {c.status === "done" && (
                <>
                  <button
                    className="btn btn-sm"
                    onClick={() => playBook(dispatch, tracks, c.id)}
                  >
                    ▶ Play
                  </button>
                  <button className="btn btn-quiet btn-sm" onClick={() => void download(c)}>
                    ↓
                  </button>
                </>
              )}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
