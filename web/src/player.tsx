/* Persistent audio player: context + bottom bar. Survives navigation, auto-advances. */
import {
  createContext, useContext, useEffect, useReducer, useRef, useState,
} from "react";
import { Link } from "react-router-dom";
import { audioUrl } from "./api";
import {
  current, initialPlayer, playerReducer, SPEEDS,
  type PlayerAction, type PlayerState, type Track,
} from "./playerState";
import styles from "./player.module.css";

const PlayerCtx = createContext<{
  state: PlayerState;
  dispatch: React.Dispatch<PlayerAction>;
}>({ state: initialPlayer, dispatch: () => {} });

export const usePlayer = () => useContext(PlayerCtx);

export function playBook(
  dispatch: React.Dispatch<PlayerAction>, tracks: Track[], chapterId: number,
) {
  const index = tracks.findIndex((t) => t.chapterId === chapterId);
  dispatch({ type: "PLAY_QUEUE", queue: tracks, index: Math.max(index, 0) });
}

export function PlayerProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(playerReducer, initialPlayer);
  return (
    <PlayerCtx.Provider value={{ state, dispatch }}>
      {children}
      <PlayerBar />
    </PlayerCtx.Provider>
  );
}

const fmt = (s: number) => {
  if (!isFinite(s)) return "0:00";
  const m = Math.floor(s / 60), sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
};

function PlayerBar() {
  const { state, dispatch } = usePlayer();
  const audioRef = useRef<HTMLAudioElement>(null);
  const [time, setTime] = useState(0);
  const [dur, setDur] = useState(0);
  const track = current(state);

  useEffect(() => {
    const a = audioRef.current;
    if (!a || !track) return;
    let cancelled = false;
    audioUrl(track.chapterId).then((url) => {
      if (cancelled) return;
      a.src = url;
      a.playbackRate = state.speed;
      if (state.playing) void a.play().catch(() => dispatch({ type: "TOGGLE" }));
    });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [track?.chapterId]);

  useEffect(() => {
    const a = audioRef.current;
    if (!a) return;
    if (state.playing) void a.play().catch(() => {});
    else a.pause();
  }, [state.playing]);

  useEffect(() => {
    if (audioRef.current) audioRef.current.playbackRate = state.speed;
  }, [state.speed]);

  if (!track) return null;
  return (
    <div className={styles.bar} role="region" aria-label="Audio player">
      <audio
        ref={audioRef}
        onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
        onDurationChange={(e) => setDur(e.currentTarget.duration)}
        onEnded={() => dispatch({ type: "ENDED" })}
      />
      <div className={styles.meta}>
        <Link to={`/books/${track.bookId}`} className={styles.title}>{track.title}</Link>
        <span className="muted">{track.bookTitle}</span>
      </div>
      <div className={styles.controls}>
        <button className="btn btn-quiet btn-sm" aria-label="Back 30 seconds"
          onClick={() => { if (audioRef.current) audioRef.current.currentTime -= 30; }}>
          ↺30
        </button>
        <button className={styles.playBtn} aria-label={state.playing ? "Pause" : "Play"}
          onClick={() => dispatch({ type: "TOGGLE" })}>
          {state.playing ? "❚❚" : "▶"}
        </button>
        <button className="btn btn-quiet btn-sm" aria-label="Forward 30 seconds"
          onClick={() => { if (audioRef.current) audioRef.current.currentTime += 30; }}>
          30↻
        </button>
      </div>
      <div className={styles.right}>
        <span className={`muted num ${styles.time}`}>{fmt(time)} / {fmt(dur)}</span>
        <input
          className={styles.seek} type="range" min={0} max={dur || 0} value={time}
          aria-label="Seek"
          onChange={(e) => {
            if (audioRef.current) audioRef.current.currentTime = +e.target.value;
          }}
        />
        <select
          className={styles.speed} value={state.speed} aria-label="Playback speed"
          onChange={(e) => dispatch({ type: "SPEED", speed: +e.target.value })}
        >
          {SPEEDS.map((s) => <option key={s} value={s}>{s}×</option>)}
        </select>
        <button className="btn btn-quiet btn-sm" aria-label="Close player"
          onClick={() => dispatch({ type: "CLOSE" })}>✕</button>
      </div>
    </div>
  );
}
