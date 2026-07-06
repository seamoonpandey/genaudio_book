import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ApiError, googleLogin, sendMagic, verifyMagic } from "../api";
import styles from "./Login.module.css";

const GOOGLE_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined;

export function Login() {
  const nav = useNavigate();
  const loc = useLocation();
  const qc = useQueryClient();
  const [email, setEmail] = useState("");
  const [msg, setMsg] = useState<{ text: string; error?: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  const handled = useRef(false);

  const dest = (loc.state as { from?: string } | null)?.from || "/library";
  const finish = () => {
    void qc.invalidateQueries({ queryKey: ["me"] });
    nav(dest, { replace: true });
  };

  // magic-link token or Google ?code= in the URL
  useEffect(() => {
    if (handled.current) return;
    const params = new URLSearchParams(loc.search);
    const token = params.get("token");
    const code = params.get("code");
    if (!token && !code) return;
    handled.current = true;
    setBusy(true);
    const p = token
      ? verifyMagic(token)
      : googleLogin(code!, `${location.origin}/login`);
    p.then(finish).catch((e: unknown) => {
      setBusy(false);
      setMsg({ text: e instanceof ApiError ? e.message : "sign-in failed", error: true });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loc.search]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      const r = await sendMagic(email);
      if (r.dev_token) {
        await verifyMagic(r.dev_token); // DEV_LOGIN mode: no email round-trip
        finish();
        return;
      }
      setMsg({ text: "Link sent. Check your email — it works for 15 minutes." });
    } catch (err) {
      setMsg({ text: err instanceof ApiError ? err.message : "could not send link", error: true });
    } finally {
      setBusy(false);
    }
  };

  const google = () => {
    const q = new URLSearchParams({
      client_id: GOOGLE_ID!,
      redirect_uri: `${location.origin}/login`,
      response_type: "code",
      scope: "openid email",
    });
    location.href = `https://accounts.google.com/o/oauth2/v2/auth?${q}`;
  };

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <h1 className={styles.brand}>genaudi</h1>
        <p className="muted">Sign in to your library</p>
        {GOOGLE_ID && (
          <>
            <button className="btn" onClick={google} disabled={busy}>
              Continue with Google
            </button>
            <div className={styles.or}><span>or</span></div>
          </>
        )}
        <form onSubmit={submit} className={styles.form}>
          <input
            className="input" type="email" required placeholder="you@example.com"
            value={email} onChange={(e) => setEmail(e.target.value)} aria-label="Email"
          />
          <button className="btn btn-primary" disabled={busy || !email}>
            Email me a sign-in link
          </button>
        </form>
        {msg && (
          <p className={msg.error ? styles.error : styles.ok} role="status">{msg.text}</p>
        )}
      </div>
    </div>
  );
}
