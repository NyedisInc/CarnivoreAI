import { resourcePush } from '../../lib/resource-push/boot';
import { ApiError } from '../../opscenter/api/auth.svelte';

export interface BoardCardFile { file_id: string; name: string; revision: string; removed: boolean }

export type BoardAttachmentsReader = (slug: string) => Promise<BoardCardFile[]>;

export interface BoardAttachmentsSource { read: BoardAttachmentsReader; topic: string }

export type BoardFilesListener = (files: BoardCardFile[]) => void;

const POLL_MS = 15000;

let source: BoardAttachmentsSource | null = null;
let isOn: () => boolean = () => true;

interface Entry {
  files: BoardCardFile[] | null; listeners: Set<BoardFilesListener>; inflight: Promise<void> | null; stop: (() => void) | null;
  started: number; published: number; epoch: number;
}
const entries = new Map<string, Entry>();

function publish(entry: Entry, files: BoardCardFile[]): void {
  entry.files = files;
  for (const listener of [...entry.listeners]) listener(files);
}

function arm(slug: string, entry: Entry): void {
  entry.stop?.();
  entry.stop = null;
  const live = boardAttachmentsSource();
  if (live) entry.stop = resourcePush().pushOrPoll(() => void refresh(slug, false), POLL_MS, [live.topic]);
}

async function refresh(slug: string, coalesce: boolean): Promise<void> {
  const entry = entries.get(slug);
  if (!entry) return;
  const live = boardAttachmentsSource();
  if (!live) {
    entry.epoch += 1;
    publish(entry, []);
    return;
  }
  if (coalesce && entry.inflight) return entry.inflight;
  const ticket = ++entry.started;
  const epoch = entry.epoch;
  const run = (async (): Promise<void> => {
    try {
      const files = await live.read(slug);
      if (epoch === entry.epoch && ticket > entry.published && entries.get(slug) === entry) {
        entry.published = ticket;
        publish(entry, files);
      }
    } catch (error) {
      if (!(error instanceof ApiError)) throw error;
    } finally {
      if (entry.inflight === run) entry.inflight = null;
    }
  })();
  entry.inflight = run;
  return run;
}

export function registerBoardAttachments(next: BoardAttachmentsSource, enabled: () => boolean = () => true): void {
  const same = next === source;
  source = next;
  isOn = enabled;
  for (const [slug, entry] of entries) {
    if (same && entry.stop) continue;
    arm(slug, entry);
    void refresh(slug, false);
  }
}

export function boardAttachmentsSource(): BoardAttachmentsSource | null {
  return source !== null && isOn() ? source : null;
}

export function unregisterBoardAttachments(): void {
  source = null;
  isOn = () => true;
  for (const entry of entries.values()) {
    entry.stop?.();
    entry.stop = null;
    entry.epoch += 1;
    publish(entry, []);
  }
}

export function subscribeBoardFiles(slug: string, listener: BoardFilesListener): () => void {
  let entry = entries.get(slug);
  if (!entry) {
    entry = { files: null, listeners: new Set(), inflight: null, stop: null, started: 0, published: 0, epoch: 0 };
    entries.set(slug, entry);
  }
  entry.listeners.add(listener);
  const answered = entry.files !== null;
  if (entry.files !== null) listener(entry.files);
  if (entry.listeners.size === 1) arm(slug, entry);
  if (!answered) void refresh(slug, true);
  return () => {
    const mine = entries.get(slug);
    if (!mine) return;
    mine.listeners.delete(listener);
    if (mine.listeners.size > 0) return;
    mine.stop?.();
    mine.epoch += 1;
    entries.delete(slug);
  };
}

export function resetBoardAttachments(): void {
  for (const entry of entries.values()) entry.stop?.();
  entries.clear();
  source = null;
  isOn = () => true;
}
