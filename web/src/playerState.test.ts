import { expect, test } from "vitest";
import { current, initialPlayer, playerReducer, type Track } from "./playerState";

const t = (n: number): Track => ({ chapterId: n, title: `Ch ${n}`, bookId: "b", bookTitle: "B" });
const queue = [t(1), t(2), t(3)];

test("play queue starts at given index", () => {
  const s = playerReducer(initialPlayer, { type: "PLAY_QUEUE", queue, index: 1 });
  expect(current(s)?.chapterId).toBe(2);
  expect(s.playing).toBe(true);
});

test("ended auto-advances, stops at end of book", () => {
  let s = playerReducer(initialPlayer, { type: "PLAY_QUEUE", queue, index: 1 });
  s = playerReducer(s, { type: "ENDED" });
  expect(current(s)?.chapterId).toBe(3);
  expect(s.playing).toBe(true);
  s = playerReducer(s, { type: "ENDED" });
  expect(current(s)?.chapterId).toBe(3);
  expect(s.playing).toBe(false);
});

test("prev clamps at start; toggle without track is a no-op", () => {
  let s = playerReducer(initialPlayer, { type: "PLAY_QUEUE", queue, index: 0 });
  s = playerReducer(s, { type: "PREV" });
  expect(s.index).toBe(0);
  expect(playerReducer(initialPlayer, { type: "TOGGLE" })).toEqual(initialPlayer);
});

test("speed only accepts known steps", () => {
  let s = playerReducer(initialPlayer, { type: "SPEED", speed: 1.5 });
  expect(s.speed).toBe(1.5);
  s = playerReducer(s, { type: "SPEED", speed: 33 });
  expect(s.speed).toBe(1);
});
