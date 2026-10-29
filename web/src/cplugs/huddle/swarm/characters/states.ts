import type { CoronaKey, ShapeKey } from './shapes';

export const STATUS_STATES = [
  'working',
  'working_subagent',
  'question',
  'notice',
  'finished_unread',
  'idle',
  'dead',
  'unknown',
] as const;

export const EVENT_STATES = [
  'asleep',
  'startup_gate',
  'question_waiting',
  'done',
  'talking',
  'escalating',
  'learning',
  'promoted',
] as const;

export const ALERT_STATES = ['alert_routine', 'alert_priority', 'alert_immediate', 'alert_flash'] as const;

export type CharacterState = (typeof STATUS_STATES)[number] | (typeof EVENT_STATES)[number] | (typeof ALERT_STATES)[number];

export const ALL_STATES: readonly CharacterState[] = [...STATUS_STATES, ...EVENT_STATES, ...ALERT_STATES];

export type GazePolicy = 'wander' | 'read' | 'up' | 'you' | 'upleft' | 'partner' | 'dart' | 'none';

export interface MorphSpec {
  keys: readonly ShapeKey[];
  keyTimes: readonly number[];
  dur: number;
  spline?: string;
}

export interface StateDef {
  kind: 'loop' | 'waiting' | 'on change' | 'rest';
  animation: string;
  gaze: GazePolicy;
  release?: number;
  morph?: MorphSpec;
  rest?: ShapeKey;
  still?: ShapeKey;
  cor?: CoronaKey;
  dots?: boolean;
  glow?: boolean;
  comet?: 'up' | 'down';
  talk?: boolean;
  quirk?: boolean;
  breath?: boolean;
  stillGaze?: readonly [number, number];
}

export const STATES: Readonly<Record<CharacterState, StateDef>> = {
  working: { kind: 'loop', animation: 'think-orbit', gaze: 'read', dots: true, stillGaze: [0.25, 0.55] },
  working_subagent: {
    kind: 'loop',
    animation: 'subagent-morph',
    gaze: 'read',
    morph: { keys: ['sq', 'hex', 'tri', 'sq'], keyTimes: [0, 0.3, 0.62, 1], dur: 1.6 },
    stillGaze: [0.25, 0.55],
  },
  question: {
    kind: 'waiting',
    animation: 'ask',
    gaze: 'up',
    rest: 'qmark',
    morph: { keys: ['sq', 'qmark', 'qmark'], keyTimes: [0, 0.16, 1], dur: 2.2 },
    stillGaze: [0, -0.7],
  },
  notice: { kind: 'on change', animation: 'perk', gaze: 'you' },
  finished_unread: { kind: 'on change', animation: 'hop', gaze: 'you', glow: true, stillGaze: [0, -0.1] },
  idle: { kind: 'rest', animation: 'rest', gaze: 'wander', quirk: true },
  dead: {
    kind: 'rest',
    animation: 'bury',
    gaze: 'none',
    rest: 'grave',
    morph: { keys: ['sq', 'grave'], keyTimes: [0, 1], dur: 1, spline: '.55 0 .85 .5' },
  },
  unknown: { kind: 'rest', animation: 'hollow', gaze: 'none' },
  asleep: { kind: 'rest', animation: 'sink', gaze: 'none', breath: true },
  startup_gate: { kind: 'waiting', animation: 'knock', gaze: 'none', rest: 'dot' },
  question_waiting: {
    kind: 'waiting',
    animation: 'lean-sway',
    gaze: 'you',
    rest: 'tear',
    morph: { keys: ['sq', 'tear'], keyTimes: [0, 1], dur: 0.6 },
    stillGaze: [0.2, -0.45],
  },
  done: { kind: 'on change', animation: 'done-spin', gaze: 'wander' },
  talking: { kind: 'loop', animation: 'talk', gaze: 'partner', talk: true },
  escalating: { kind: 'on change', animation: 'launch', gaze: 'up', release: 1.9, comet: 'up', stillGaze: [0, -1] },
  learning: { kind: 'on change', animation: 'gulp', gaze: 'upleft', release: 2.3, comet: 'down', stillGaze: [-0.6, -0.85] },
  promoted: { kind: 'on change', animation: 'grow', gaze: 'up', release: 2, stillGaze: [0, -0.7] },
  alert_routine: { kind: 'on change', animation: 'bristle', gaze: 'wander', cor: 'routine' },
  alert_priority: { kind: 'waiting', animation: 'pulse', gaze: 'you', cor: 'priority' },
  alert_immediate: { kind: 'waiting', animation: 'shake', gaze: 'you', cor: 'immediate' },
  alert_flash: { kind: 'waiting', animation: 'freak', gaze: 'dart', cor: 'flash' },
};

export const ANIMATIONS: readonly string[] = ALL_STATES.map((s) => STATES[s].animation);

export function drawnState(state: CharacterState, picks: Readonly<Partial<Record<string, string>>>): { state: CharacterState; still: boolean } {
  const pick = picks[state];
  if (pick === 'none') return { state, still: true };
  const owner = pick ? ALL_STATES.find((s) => STATES[s].animation === pick) : undefined;
  return { state: owner ?? state, still: false };
}

export type Tell = 'question' | 'notice' | 'question_waiting' | 'unread';

export function sendState(tell: Tell): CharacterState {
  return tell === 'unread' ? 'finished_unread' : tell;
}

export function animationOf(state: CharacterState): string {
  return STATES[state].animation;
}

export function resolveState(raw: string | null | undefined): CharacterState {
  return raw && Object.prototype.hasOwnProperty.call(STATES, raw) ? (raw as CharacterState) : 'unknown';
}

export function heldShape(state: CharacterState, home: ShapeKey = 'sq'): ShapeKey {
  return STATES[state].rest ?? home;
}

export interface MorphPlan {
  keys: readonly ShapeKey[];
  keyTimes: readonly number[];
  dur: number;
  spline: string;
}

export const DEFAULT_SPLINE = '.45 0 .25 1';

export function planMorph(state: CharacterState, held: ShapeKey | null, home: ShapeKey = 'sq'): MorphPlan | null {
  const def = STATES[state];
  if (def.morph) {
    const own = def.morph.keys.map((k) => (k === 'sq' ? home : k));
    const keys = held && held !== home && own[0] === home ? [held, ...own.slice(1)] : own;
    return { keys, keyTimes: def.morph.keyTimes, dur: def.morph.dur, spline: def.morph.spline ?? DEFAULT_SPLINE };
  }
  const target = heldShape(state, home);
  if (held && held !== target) return { keys: [held, target], keyTimes: [0, 1], dur: 0.4, spline: DEFAULT_SPLINE };
  return null;
}
