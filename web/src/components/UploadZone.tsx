/* Drop zone + whole-page drag catcher. Accepts .pdf/.epub, hands the File up. */
import { useEffect, useRef, useState } from "react";
import styles from "./UploadZone.module.css";

const OK = [".pdf", ".epub"];

export function UploadZone({
  onFile, big = false, disabled = false,
}: { onFile: (f: File) => void; big?: boolean; disabled?: boolean }) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const take = (f: File | undefined | null) => {
    if (!f || disabled) return;
    if (!OK.some((ext) => f.name.toLowerCase().endsWith(ext))) return;
    onFile(f);
  };

  useEffect(() => {
    if (disabled) return;
    let depth = 0;
    const enter = (e: DragEvent) => { e.preventDefault(); depth++; setOver(true); };
    const leave = () => { if (--depth <= 0) { depth = 0; setOver(false); } };
    const overH = (e: DragEvent) => e.preventDefault();
    const drop = (e: DragEvent) => {
      e.preventDefault();
      depth = 0;
      setOver(false);
      take(e.dataTransfer?.files[0]);
    };
    document.addEventListener("dragenter", enter);
    document.addEventListener("dragleave", leave);
    document.addEventListener("dragover", overH);
    document.addEventListener("drop", drop);
    return () => {
      document.removeEventListener("dragenter", enter);
      document.removeEventListener("dragleave", leave);
      document.removeEventListener("dragover", overH);
      document.removeEventListener("drop", drop);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [disabled]);

  return (
    <button
      type="button"
      className={`${styles.zone} ${big ? styles.big : ""} ${over ? styles.over : ""}`}
      onClick={() => input.current?.click()}
      disabled={disabled}
    >
      <input
        ref={input} type="file" accept=".pdf,.epub" hidden
        onChange={(e) => { take(e.target.files?.[0]); e.target.value = ""; }}
      />
      <span className={styles.glyph} aria-hidden="true">⇪</span>
      <span className={styles.label}>
        {over ? "Drop it here" : "Drop a PDF or EPUB — or click to choose"}
      </span>
      <span className="muted">Up to 25 MB. Chapters are detected automatically.</span>
    </button>
  );
}
