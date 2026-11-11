import type { Env, MotionStats } from './types';

const MAX_DT = 1 / 30;
const FIRST_DT = 1 / 60;
const WORK_WINDOW = 400;

export interface FrameLoop {
  wake(): void;
  noteRender(): void;
  stats(): MotionStats;
  stop(): void;
}

export function createFrameLoop(env: Env, tick: (dt: number, t: number) => boolean): FrameLoop {
  let handle = 0;
  let last = 0;
  let frames = 0;
  let renders = 0;
  const work: number[] = [];

  const frame = (t: number): void => {
    handle = 0;
    frames++;
    const w0 = env.now();
    const dt = last ? Math.min((t - last) / 1000, MAX_DT) : FIRST_DT;
    last = t;
    const moving = tick(dt, t);
    work.push(env.now() - w0);
    if (work.length > WORK_WINDOW) work.shift();
    if (moving) handle = env.raf(frame);
    else last = 0;
  };

  return {
    wake() {
      if (handle) return;
      last = 0;
      handle = env.raf(frame);
    },
    noteRender() {
      renders++;
    },
    stats() {
      const sorted = [...work].sort((a, b) => a - b);
      const p95 = sorted.length ? (sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))] ?? 0) : 0;
      return { running: handle !== 0, frames, renders, workP95: p95, workMax: sorted.length ? (sorted[sorted.length - 1] ?? 0) : 0 };
    },
    stop() {
      if (handle) env.caf(handle);
      handle = 0;
      last = 0;
    },
  };
}
