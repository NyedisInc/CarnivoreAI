
export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface Point {
  x: number;
  y: number;
}

export type ItemId = string;

export type Edge = 'n' | 's' | 'e' | 'w' | 'ne' | 'nw' | 'se' | 'sw';

export type Source =
  | { kind: 'move'; id: ItemId }
  | { kind: 'resize'; id: ItemId; edge: Edge }
  | { kind: 'divider'; id: string }
  | { kind: 'external'; id: ItemId };

export type Via = 'pointer' | 'keyboard' | 'external';

export interface GestureState {
  source: Source;
  pointer: Point;
  start: Point;
  delta: Point;
  grab: Point;
  startRect: Rect | null;
  base: ReadonlyMap<ItemId, Rect>;
  bounds: { w: number; h: number };
  outside: boolean;
}

export interface Target {
  key: string;
  rects: ReadonlyMap<ItemId, Rect>;
  landing?: Rect | null;
  valid?: boolean;
  instant?: boolean;
  payload?: unknown;
  mark?: { label: string; kind: string };
}

export interface KeyStep {
  dir: 'left' | 'right' | 'up' | 'down';
  resize: boolean;
}

export interface Adapter {
  rects(): ReadonlyMap<ItemId, Rect>;
  hit(el: Element, ev: PointerEvent): Source | null;
  targetKey(g: GestureState): string;
  preview(g: GestureState, key: string): Target;
  activeRect?(g: GestureState): Rect;
  begin?(source: Source, via: Via): void;
  commit(target: Target, g: GestureState | null): void;
  cancel(): void;
  step?(id: ItemId, step: KeyStep, from?: Target | null): Target | null;
  stepFromTarget?: boolean;
  extent?(rects: ReadonlyMap<ItemId, Rect>): number | null;
  label?(id: ItemId): string;
}

export type RenderReason = 'mount' | 'resize' | 'settle';

export interface RenderSize {
  w: number;
  h: number;
}

export interface Env {
  raf(cb: (t: number) => void): number;
  caf(id: number): void;
  now(): number;
  win: Window;
  doc: Document;
}

export interface MotionOptions {
  enabled?: boolean;
  render?(id: ItemId, size: RenderSize, reason: RenderReason): void;
  scroller?: HTMLElement | null;
  autoscroll?: boolean;
  reduced?: () => boolean;
  sizePaint?: 'layout' | 'flip';
  lift?: { tilt: boolean; maxW: number; maxH: number };
  translate?: (key: string, params?: Record<string, unknown>) => string;
  env?: Env;
}

export type MotionEvent = 'settle' | 'dragstart' | 'dragend' | 'resizestart' | 'resizeend';

export interface MotionStats {
  running: boolean;
  frames: number;
  renders: number;
  workP95: number;
  workMax: number;
}

export interface ExternalOptions {
  as?: 'move';
  leaveOnDrop?: boolean;
}

export interface MotionHandle {
  register(id: ItemId, el: HTMLElement): void;
  unregister(id: ItemId): void;
  sync(instant?: boolean): void;
  setEnabled(on: boolean): void;
  isBusy(): boolean;
  beginExternal(source: { id: ItemId; rect: Rect; grab: Point }, ev: PointerEvent, opts?: ExternalOptions): boolean;
  on(event: MotionEvent, fn: (detail: { id: string; cancelled?: boolean }) => void): () => void;
  stats(): MotionStats;
  destroy(): void;
}
