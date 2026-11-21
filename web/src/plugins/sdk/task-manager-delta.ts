import { resourcePush } from '../../lib/resource-push/boot';
import { LIVENESS } from '../../lib/resource-push/store';
import { onEventFrame } from './terminal';

export const DATA_FRAME = 'cplug.data';
export const DELTA_TOPIC = 'cplug.huddle.delta';
export const TASK_MANAGER_LIST_FAMILY = 'cplug.huddle.list';
export const KEEP_FRAMES = 32;
export const RESYNC_JITTER_MS = 4_000;

export interface TaskManagerDeltaItem {
  id: number;
  list: string;
  state?: string;
  status?: string;
  owner_session_key?: string;
}

export interface TaskManagerListDeltaOf<Item extends { id: number }, Group, Inbox> {
  list: string;
  revision: number;
  groups: Group[];
  inbox: Inbox[] | null;
  order: number[];
  numbers: Record<string, number | null>;
  swarm?: number[];
  items: Item[];
  deleted: number[];
  done_count?: number;
  done_swarm?: number;
}

export interface TaskManagerDeltaOf<List, Row> {
  seq: number;
  epoch: string;
  resync?: boolean;
  lists?: List[];
  list_rows?: Row[];
}

export type TaskManagerDeltaWire = TaskManagerDeltaOf<TaskManagerListDeltaOf<TaskManagerDeltaItem, unknown, unknown>, unknown>;

export interface DeltaHead {
  seq: number;
  epoch: string;
  resync?: boolean;
}

export interface DeltaMarker {
  delta_seq?: number;
  delta_epoch?: string;
}

export function deltaOf<D extends DeltaHead = TaskManagerDeltaWire>(frame: unknown): D | null {
  const f = frame as { type?: unknown; topic?: unknown; data?: Partial<DeltaHead> } | null;
  if (!f || f.type !== DATA_FRAME || f.topic !== DELTA_TOPIC || !f.data) return null;
  const data = f.data;
  return typeof data.seq === 'number' && typeof data.epoch === 'string' ? (data as D) : null;
}

export class DeltaSequence<D extends DeltaHead = TaskManagerDeltaWire> {
  private epoch: string | null = null;
  private last: number | null = null;
  private floors: Record<string, number> = {};
  private kept: D[] = [];

  receive(delta: D): 'apply' | 'stale' | 'gap' {
    if (this.epoch !== null && delta.epoch !== this.epoch) {
      this.reset(delta.epoch, delta.seq);
      this.kept = [delta];
      return 'gap';
    }
    this.epoch = delta.epoch;
    if (this.last !== null && delta.seq <= this.last) return 'stale';
    this.kept = [...this.kept, delta].slice(-KEEP_FRAMES);
    const gap = this.last !== null && delta.seq !== this.last + 1;
    this.last = delta.seq;
    return gap ? 'gap' : 'apply';
  }

  laneTakes(lane: string, delta: D): boolean {
    const floor = this.floors[lane];
    return floor === undefined || delta.seq > floor;
  }

  read(lane: string, marker: DeltaMarker): D[] {
    const seq = marker.delta_seq;
    const epoch = marker.delta_epoch;
    if (typeof seq !== 'number' || typeof epoch !== 'string') return [];
    if (this.epoch !== epoch) this.reset(epoch, seq);
    else if (this.last === null) this.last = seq;
    this.floors[lane] = seq;
    return this.kept.filter((d) => d.seq > seq && !d.resync);
  }

  private reset(epoch: string, seq: number): void {
    this.epoch = epoch;
    this.last = seq;
    this.floors = {};
    this.kept = [];
  }
}

export function deltaLive(): boolean {
  return resourcePush().isLive?.(DELTA_TOPIC) === true;
}

export function deltaTouchesIds(delta: TaskManagerDeltaWire, ids: ReadonlySet<number>): boolean {
  if (!ids.size) return false;
  return (delta.lists ?? []).some((entry) => entry.deleted.some((id) => ids.has(id)) || entry.items.some((item) => ids.has(item.id)));
}

export interface DeltaFollower {
  touches(delta: TaskManagerDeltaWire): boolean;
  fallback(topic: string): boolean;
  refresh(): void;
  reconnect?: boolean;
}

export function followTaskManagerDelta(follower: DeltaFollower): () => void {
  const sequence = new DeltaSequence();
  let resyncTimer: ReturnType<typeof setTimeout> | null = null;
  const offTopics = resourcePush().onChange((topics) => {
    if (deltaLive()) {
      if (follower.reconnect && topics.includes(LIVENESS)) follower.refresh();
      return;
    }
    if (topics.some((topic) => follower.fallback(topic))) follower.refresh();
  });
  const offFrames = onEventFrame(DATA_FRAME, (frame) => {
    const delta = deltaOf(frame);
    if (!delta) return;
    const verdict = sequence.receive(delta);
    if (verdict === 'stale') return;
    if (verdict === 'gap') {
      follower.refresh();
    } else if (delta.resync) {
      resyncTimer ??= setTimeout(() => {
        resyncTimer = null;
        follower.refresh();
      }, Math.random() * RESYNC_JITTER_MS);
    } else if (follower.touches(delta)) {
      follower.refresh();
    }
  });
  return () => {
    offTopics();
    offFrames();
    if (resyncTimer) clearTimeout(resyncTimer);
    resyncTimer = null;
  };
}
