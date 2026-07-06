import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, deleteBook, listBooks, uploadBook } from "../api";
import { Cover } from "../components/Cover";
import { Modal } from "../components/Modal";
import { UploadZone } from "../components/UploadZone";
import type { BookSummary } from "../types";
import styles from "./Library.module.css";

const hrs = (s: number) => (s >= 3600 ? `${(s / 3600).toFixed(1)} h` : `${Math.round(s / 60)} min`);

export function Library() {
  const qc = useQueryClient();
  const { data: books } = useQuery({ queryKey: ["books"], queryFn: listBooks });
  const [toDelete, setToDelete] = useState<BookSummary | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const up = useMutation({
    mutationFn: uploadBook,
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["books"] }),
    onError: (e) => setErr(e instanceof ApiError ? e.message : "upload failed"),
  });
  const del = useMutation({
    mutationFn: deleteBook,
    onSuccess: () => {
      setToDelete(null);
      void qc.invalidateQueries({ queryKey: ["books"] });
    },
  });

  const onFile = (f: File) => {
    setErr(null);
    up.mutate(f);
  };

  return (
    <div className="container">
      <div className={styles.head}>
        <h1>Library</h1>
      </div>

      {books?.length === 0 && !up.isPending ? (
        <UploadZone onFile={onFile} big />
      ) : (
        <UploadZone onFile={onFile} disabled={up.isPending} />
      )}
      {err && <p className={styles.error} role="alert">{err}</p>}

      <div className={styles.grid}>
        {up.isPending && (
          <div className={`${styles.card} ${styles.extracting}`}>
            <div className={styles.coverGhost} />
            <div className={styles.cardBody}>
              <strong>Reading your book…</strong>
              <span className="muted">detecting chapters</span>
            </div>
          </div>
        )}
        {books?.map((b) => (
          <div key={b.id} className={styles.card}>
            <Link to={`/books/${b.id}`} className={styles.coverLink}>
              <Cover title={b.title} />
            </Link>
            <div className={styles.cardBody}>
              <Link to={`/books/${b.id}`} className={styles.title}>{b.title}</Link>
              <span className="muted num">
                {b.chapters_done}/{b.chapters_total} chapters converted
                {b.duration > 0 && ` · ${hrs(b.duration)}`}
              </span>
              <div className={styles.progress} aria-hidden="true">
                <span style={{ width: `${(b.chapters_done / Math.max(b.chapters_total, 1)) * 100}%` }} />
              </div>
              <button
                className={`btn btn-quiet btn-sm btn-danger ${styles.del}`}
                onClick={() => setToDelete(b)}
              >
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>

      {toDelete && (
        <Modal title={`Delete “${toDelete.title}”?`} onClose={() => setToDelete(null)}>
          <p className="muted">
            Removes the book, its {toDelete.chapters_total} chapters and all converted audio.
            This can't be undone.
          </p>
          <div style={{ display: "flex", gap: "0.6rem", justifyContent: "flex-end" }}>
            <button className="btn" onClick={() => setToDelete(null)}>Keep it</button>
            <button
              className="btn btn-primary" disabled={del.isPending}
              onClick={() => del.mutate(toDelete.id)}
            >
              Delete book
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
