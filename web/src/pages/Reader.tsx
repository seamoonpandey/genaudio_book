import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { getChapterText } from "../api";
import { toggleTheme } from "../App";
import styles from "./Reader.module.css";

const SIZES = [0.95, 1.08, 1.22, 1.4];

export function Reader() {
  const { bookId = "", idx = "0" } = useParams();
  const i = parseInt(idx, 10);
  const nav = useNavigate();
  const { data: ch } = useQuery({
    queryKey: ["chapter", bookId, i],
    queryFn: () => getChapterText(bookId, i),
  });

  const sizeKey = "genaudi-reader-size";
  const posKey = `genaudi-pos-${bookId}-${i}`;

  useEffect(() => {
    const saved = Number(sessionStorage.getItem(posKey) ?? localStorage.getItem(posKey) ?? 0);
    if (ch && saved > 0) window.scrollTo(0, saved);
    const save = () => localStorage.setItem(posKey, String(window.scrollY));
    window.addEventListener("scrollend", save);
    return () => window.removeEventListener("scrollend", save);
  }, [ch, posKey]);

  const setSize = (delta: number) => {
    const cur = Number(localStorage.getItem(sizeKey) ?? 1);
    const next = SIZES[Math.min(Math.max(SIZES.indexOf(cur) + delta, 0), SIZES.length - 1)] ?? 1.08;
    localStorage.setItem(sizeKey, String(next));
    document.documentElement.style.setProperty("--reader-size", `${next}rem`);
  };
  useEffect(() => {
    const cur = localStorage.getItem(sizeKey);
    if (cur) document.documentElement.style.setProperty("--reader-size", `${cur}rem`);
  }, []);

  if (!ch) return null;
  const paras = ch.text.split(/\n\n+/).filter((p) => p.trim());

  return (
    <div className={styles.page}>
      <div className={styles.toolbar}>
        <Link to={`/books/${bookId}`} className="btn btn-quiet btn-sm">← Chapters</Link>
        <span className={`muted num ${styles.pos}`}>{i + 1} / {ch.total}</span>
        <div className={styles.tools}>
          <button className="btn btn-quiet btn-sm" onClick={() => setSize(-1)} aria-label="Smaller text">A−</button>
          <button className="btn btn-quiet btn-sm" onClick={() => setSize(1)} aria-label="Larger text">A+</button>
          <button className="btn btn-quiet btn-sm" onClick={toggleTheme} aria-label="Toggle theme">◐</button>
        </div>
      </div>

      <article className={styles.article}>
        <h1>{ch.title}</h1>
        {paras.map((p, n) => (
          <p key={n} className={n === 0 ? styles.first : undefined}>{p}</p>
        ))}
      </article>

      <nav className={styles.pager}>
        <button
          className="btn" disabled={i === 0}
          onClick={() => { window.scrollTo(0, 0); nav(`/books/${bookId}/read/${i - 1}`); }}
        >
          ← Previous
        </button>
        <button
          className="btn" disabled={i + 1 >= ch.total}
          onClick={() => { window.scrollTo(0, 0); nav(`/books/${bookId}/read/${i + 1}`); }}
        >
          Next →
        </button>
      </nav>
    </div>
  );
}
