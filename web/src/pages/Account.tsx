import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, checkout, logout, portal } from "../api";
import { useMe } from "../App";
import { FREE_LIMIT } from "../types";
import styles from "./Account.module.css";

export function Account() {
  const me = useMe().data?.user;
  const qc = useQueryClient();
  const nav = useNavigate();
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!me) return null;
  const used = Math.min(me.chapters_converted, FREE_LIMIT);

  const go = async (fn: () => Promise<{ url: string }>) => {
    setBusy(true);
    setErr(null);
    try {
      location.href = (await fn()).url;
    } catch (e) {
      setBusy(false);
      setErr(e instanceof ApiError && e.status === 503
        ? "Billing isn't configured on this deployment yet."
        : e instanceof ApiError ? e.message : "something went wrong");
    }
  };

  return (
    <div className={`container ${styles.page}`}>
      <h1>Account</h1>
      <section className={styles.card}>
        <div className={styles.rowBetween}>
          <div>
            <p className={styles.email}>{me.email}</p>
            <p className="muted">
              {me.plan === "pro" ? "Pro — unlimited conversions" : "Free plan"}
            </p>
          </div>
          <span className={`chip ${me.plan === "pro" ? "chip-done" : ""}`}>
            {me.plan === "pro" ? "Pro" : "Free"}
          </span>
        </div>

        {me.payment_failed && (
          <p className={styles.warn} role="alert">
            Your last payment failed — update your card to keep Pro.
          </p>
        )}

        {me.plan === "free" && (
          <>
            <div>
              <p className="muted num" style={{ marginBottom: "0.3rem" }}>
                {used} of {FREE_LIMIT} free conversions used
              </p>
              <div className={styles.meter} aria-hidden="true">
                <span style={{ width: `${(used / FREE_LIMIT) * 100}%` }} />
              </div>
            </div>
            <button className="btn btn-primary" disabled={busy} onClick={() => void go(checkout)}>
              Upgrade to Pro — $9/month
            </button>
            <p className="muted">Unlimited conversions, every book in your library.</p>
          </>
        )}
        {me.plan === "pro" && (
          <button className="btn" disabled={busy} onClick={() => void go(portal)}>
            Manage subscription
          </button>
        )}
        {err && <p className={styles.error} role="alert">{err}</p>}
      </section>

      <button
        className="btn btn-quiet"
        onClick={async () => {
          await logout();
          await qc.invalidateQueries({ queryKey: ["me"] });
          nav("/");
        }}
      >
        Sign out
      </button>
    </div>
  );
}
