import { useEffect, useRef } from "react";
import styles from "./Modal.module.css";

export function Modal({
  title, children, onClose,
}: { title: string; children: React.ReactNode; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
  }, []);
  return (
    <dialog
      ref={ref} className={styles.modal} onClose={onClose}
      onClick={(e) => { if (e.target === ref.current) onClose(); }}
    >
      <div className={styles.inner}>
        <h2>{title}</h2>
        {children}
      </div>
    </dialog>
  );
}
