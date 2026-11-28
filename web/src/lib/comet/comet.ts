import './comet.css';
import { ledStateFor, type LedSignals } from '../led';
import { legacyGlobal } from '../legacy-globals';

export type CometKind = 'unread' | 'question' | 'notice';

export interface CometFacts {
  status: string | null;
  unread: boolean;
  startupGate: string | null;
  transport?: string | null;
}

interface CometBars {
  top: HTMLElement;
  right: HTMLElement;
  bottom: HTMLElement;
  left: HTMLElement;
}

interface CometEntry {
  host: HTMLElement;
  ring: HTMLElement;
  bars: CometBars;
  w: number;
  h: number;
  p: number;
}

interface TickerApi {
  registerComet?: (ring: HTMLElement, info: { host: HTMLElement; w: number; h: number; p: number; bars: CometBars }) => void;
  unregisterComet?: (ring: HTMLElement) => void;
}

const TAIL_FRACTION = 150 / 360;

export function cometKind(facts: CometFacts | null | undefined): CometKind | null {
  if (!facts) return null;
  const signals: LedSignals = { activity_status: facts.status, unread: facts.unread, startup_gate: facts.startupGate, transport: facts.transport };
  const led = ledStateFor(signals);
  if (led.inner === 'waiting-permission' || led.inner === 'waiting-input') return 'question';
  if (led.inner === 'notice' && facts.status === 'notice') return 'notice';
  if (led.outer === 'unread' || led.inner === 'asleep-unread') return 'unread';
  return null;
}

export function cometDelay(lapSeconds: number, now: number = Number(document.timeline?.currentTime ?? performance.now())): string {
  const lapMs = lapSeconds * 1000;
  return `${-((now % lapMs) / 1000)}s`;
}

const entryOf = new WeakMap<HTMLElement, CometEntry>();
const lapOf = new WeakMap<HTMLElement, number>();
let sizeObserver: ResizeObserver | null = null;

function ticker(): TickerApi | undefined {
  return legacyGlobal<TickerApi>('AmbientTicker');
}

function createRibbon(host: HTMLElement): CometEntry {
  const ring = document.createElement('span');
  ring.className = 'comet-ribbon-ring';
  ring.setAttribute('aria-hidden', 'true');
  const bars = {} as CometBars;
  (['top', 'right', 'bottom', 'left'] as const).forEach((side) => {
    const edge = document.createElement('span');
    edge.className = `comet-edge ${side}`;
    const bar = document.createElement('span');
    bar.className = 'comet-bar';
    edge.appendChild(bar);
    ring.appendChild(edge);
    bars[side] = bar;
  });
  host.appendChild(ring);
  const entry: CometEntry = { host, ring, bars, w: 0, h: 0, p: 0 };
  entryOf.set(host, entry);
  return entry;
}

function syncRibbonSize(el: HTMLElement): void {
  const entry = entryOf.get(el);
  if (!entry) return;
  const { width, height } = el.getBoundingClientRect();
  if (height > 0 && width > 0) {
    const p = 2 * width + 2 * height;
    const tailLen = p * TAIL_FRACTION;
    const cs = typeof getComputedStyle === 'function' ? getComputedStyle(el) : null;
    const radius = Math.min(parseFloat(cs?.borderTopLeftRadius || '0') || 0, width / 2, height / 2);
    const miter = Math.min(Math.max(Math.ceil(radius) + 2, 4), Math.floor(Math.min(width, height) / 2));
    entry.w = width;
    entry.h = height;
    entry.p = p;
    entry.ring.style.setProperty('--cm-p', `${p.toFixed(2)}px`);
    entry.ring.style.setProperty('--cm-l', `${tailLen.toFixed(2)}px`);
    entry.ring.style.setProperty('--cm-m', `${miter}px`);
    el.style.setProperty('--oc-comet-aspect', (width / height).toFixed(4));
    ticker()?.registerComet?.(entry.ring, { host: el, w: width, h: height, p, bars: entry.bars });
  } else {
    entry.w = 0;
    entry.h = 0;
    entry.p = 0;
    el.style.removeProperty('--oc-comet-aspect');
  }
}

function watchSize(el: HTMLElement): void {
  syncRibbonSize(el);
  if (typeof ResizeObserver === 'undefined') return;
  sizeObserver ??= new ResizeObserver((entries) => entries.forEach((e) => syncRibbonSize(e.target as HTMLElement)));
  sizeObserver.observe(el);
}

export function applyComet(el: HTMLElement, kind: CometKind | null, lapSeconds: number): void {
  if (kind === null) {
    el.removeAttribute('data-comet');
    el.style.removeProperty('--oc-comet-delay');
    el.style.removeProperty('--oc-comet-aspect');
    sizeObserver?.unobserve(el);
    const prev = entryOf.get(el);
    if (prev) {
      ticker()?.unregisterComet?.(prev.ring);
      prev.ring.remove();
      entryOf.delete(el);
    }
    lapOf.delete(el);
    return;
  }
  if (!entryOf.has(el)) createRibbon(el);
  if (lapOf.get(el) !== lapSeconds) {
    el.style.setProperty('--oc-comet-delay', cometDelay(lapSeconds));
    lapOf.set(el, lapSeconds);
  }
  el.setAttribute('data-comet', kind);
  watchSize(el);
}
