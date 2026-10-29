/* the bottom bar */
import { untrack } from 'svelte';
import { floatingShowing, ownsEscape } from '../sidebar-widgets/escape-guards';

export interface StripEscapeLayer {
  open: () => boolean;
  hide: () => void;
}

interface Entry {
  layer: StripEscapeLayer;
  stamp: number;
}

const entries = new Set<Entry>();
let opened = 0;
const floatingAtStart = new WeakSet<Event>();

function newestOpen(list: Iterable<Entry>): Entry | null {
  let best: Entry | null = null;
  for (const entry of list) if (entry.layer.open() && (best === null || entry.stamp > best.stamp)) best = entry;
  return best;
}

const bareEscape = (event: KeyboardEvent): boolean =>
  event.key === 'Escape' && !event.isComposing && !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey;

function onCapture(event: KeyboardEvent): void {
  if (bareEscape(event) && floatingShowing(document)) floatingAtStart.add(event);
}

export function handleStripEscape(event: KeyboardEvent): boolean {
  if (!bareEscape(event) || event.defaultPrevented || floatingAtStart.has(event)) return false;
  const target = event.target;
  if (target instanceof Element && target.closest('.xterm')) return false;
  if (ownsEscape(target) || floatingShowing(document)) return false;
  const entry = newestOpen(entries);
  if (!entry) return false;
  event.preventDefault();
  entry.layer.hide();
  return true;
}

function install(): void {
  window.addEventListener('keydown', onCapture, true);
  window.addEventListener('keydown', handleStripEscape);
}

function uninstall(): void {
  window.removeEventListener('keydown', onCapture, true);
  window.removeEventListener('keydown', handleStripEscape);
}

export function useStripEscape(layer: StripEscapeLayer): void {
  const entry: Entry = { layer, stamp: 0 };
  let wasOpen = false;
  $effect(() => {
    const now = layer.open();
    untrack(() => {
      if (now && !wasOpen) entry.stamp = ++opened;
      wasOpen = now;
    });
  });
  $effect(() => {
    if (entries.size === 0) install();
    entries.add(entry);
    return () => {
      entries.delete(entry);
      if (entries.size === 0) uninstall();
    };
  });
}
