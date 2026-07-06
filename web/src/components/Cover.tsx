/* Generated cloth-bound cover — the visual signature. Color hashed from title. */
import styles from "./Cover.module.css";

const hash = (s: string) => [...s].reduce((h, c) => (h * 31 + c.charCodeAt(0)) | 0, 7);

export function Cover({ title, size = "md" }: { title: string; size?: "sm" | "md" | "lg" }) {
  const cloth = Math.abs(hash(title)) % 6;
  return (
    <div
      className={`${styles.cover} ${styles[size]}`}
      style={{ background: `var(--cloth-${cloth})` }}
      aria-hidden="true"
    >
      <span className={styles.spine} />
      <span className={styles.title}>{title}</span>
      <span className={styles.rule} />
    </div>
  );
}
