/* Pure player state machine — kept free of React/DOM so it's unit-testable. */
export type Track = { chapterId: number; title: string; bookId: string; bookTitle: string };

export type PlayerState = {
  queue: Track[];
  index: number; // -1 = nothing loaded
  playing: boolean;
  speed: number;
};

export type PlayerAction =
  | { type: "PLAY_QUEUE"; queue: Track[]; index: number }
  | { type: "TOGGLE" }
  | { type: "ENDED" }
  | { type: "NEXT" }
  | { type: "PREV" }
  | { type: "SPEED"; speed: number }
  | { type: "CLOSE" };

export const SPEEDS = [0.75, 1, 1.25, 1.5, 1.75, 2];

export const initialPlayer: PlayerState = { queue: [], index: -1, playing: false, speed: 1 };

export function playerReducer(s: PlayerState, a: PlayerAction): PlayerState {
  switch (a.type) {
    case "PLAY_QUEUE":
      return { ...s, queue: a.queue, index: a.index, playing: true };
    case "TOGGLE":
      return s.index < 0 ? s : { ...s, playing: !s.playing };
    case "ENDED":
    case "NEXT":
      if (s.index < 0) return s;
      if (s.index + 1 >= s.queue.length)
        return a.type === "ENDED" ? { ...s, playing: false } : s;
      return { ...s, index: s.index + 1, playing: true };
    case "PREV":
      return s.index <= 0 ? s : { ...s, index: s.index - 1, playing: true };
    case "SPEED":
      return { ...s, speed: SPEEDS.includes(a.speed) ? a.speed : 1 };
    case "CLOSE":
      return initialPlayer;
  }
}

export const current = (s: PlayerState): Track | null =>
  s.index >= 0 && s.index < s.queue.length ? s.queue[s.index] : null;
