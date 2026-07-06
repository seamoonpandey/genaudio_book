import { Link, Navigate, useNavigate } from "react-router-dom";
import { useMe } from "../App";
import { Cover } from "../components/Cover";
import { UploadZone } from "../components/UploadZone";
import styles from "./Landing.module.css";

const STEPS = [
  ["Upload", "Drop any PDF or EPUB you own. Chapters are detected automatically."],
  ["Convert", "Pick a chapter or queue the whole book. We synthesize it in the cloud."],
  ["Listen", "Stream in the built-in player or download MP3s for the road."],
] as const;

export function Landing() {
  const { data, isLoading } = useMe();
  const nav = useNavigate();
  if (!isLoading && data?.user) return <Navigate to="/library" replace />;

  return (
    <div className={styles.page}>
      <header className={styles.nav}>
        <span className={styles.wordmark}>genaudi</span>
        <Link to="/login" className="btn btn-sm">Sign in</Link>
      </header>

      <section className={styles.hero}>
        <div className={styles.heroText}>
          <h1>Your books,<br />read aloud.</h1>
          <p className={styles.sub}>
            Turn any PDF or EPUB you own into an audiobook. Read along in a clean
            reader, listen anywhere.
          </p>
          <UploadZone onFile={() => nav("/login")} />
          <p className={styles.sampleLabel}>Hear the voice — chapter one of <em>Gatsby</em>:</p>
          <audio controls src="/sample.mp3" preload="none" className={styles.sample} />
        </div>
        <div className={styles.shelf} aria-hidden="true">
          <Cover title="The Great Gatsby" size="lg" />
          <Cover title="Meditations" size="lg" />
          <Cover title="The Odyssey" size="lg" />
        </div>
      </section>

      <section className={styles.steps}>
        {STEPS.map(([t, d]) => (
          <div key={t} className={styles.step}>
            <h3>{t}</h3>
            <p className="muted">{d}</p>
          </div>
        ))}
      </section>

      <section className={styles.pricing}>
        <h2>Pricing</h2>
        <div className={styles.plans}>
          <div className={styles.plan}>
            <h3>Free</h3>
            <p className={styles.price}>$0</p>
            <ul>
              <li>Unlimited books &amp; reading</li>
              <li>3 chapter conversions</li>
              <li>MP3 downloads</li>
            </ul>
            <Link to="/login" className="btn">Start free</Link>
          </div>
          <div className={`${styles.plan} ${styles.pro}`}>
            <h3>Pro</h3>
            <p className={styles.price}>$9<span className="muted">/month</span></p>
            <ul>
              <li>Everything in Free</li>
              <li>Unlimited conversions</li>
              <li>Whole-book queueing</li>
            </ul>
            <Link to="/login" className="btn btn-primary">Go Pro</Link>
          </div>
        </div>
      </section>

      <footer className={styles.footer}>
        <span className="muted">genaudi — for books you own. © 2026</span>
      </footer>
    </div>
  );
}
