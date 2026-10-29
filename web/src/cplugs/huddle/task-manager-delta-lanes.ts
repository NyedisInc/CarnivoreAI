import { DeltaSequence, RESYNC_JITTER_MS, deltaOf, type DeltaMarker } from '../sdk/task-manager-delta';
import { applyToBody, applyToGroups, type DeltaLane, type TaskManagerDelta } from './task-manager-delta';
import type { TaskManagerGroup, TaskManagerListBody, TaskManagerListRow } from './huddle-model';

export interface DeltaLaneHooks {
  groups(): TaskManagerGroup[] | null;
  setGroups(next: TaskManagerGroup[]): void;
  body(): TaskManagerListBody | null;
  setBody(next: TaskManagerListBody, previous: TaskManagerListBody): void;
  setLists(rows: TaskManagerListRow[]): void;
  includeSwarm(list: string): boolean;
  refresh(): void;
  writing(): boolean;
  doneTouched?(list: string): void;
}

export interface DeltaLanes {
  receive(frame: unknown): void;
  replay(lane: DeltaLane, marker: DeltaMarker): TaskManagerListRow[] | null;
  settled(): void;
}

export function createDeltaLanes(hooks: DeltaLaneHooks): DeltaLanes {
  const sequence = new DeltaSequence<TaskManagerDelta>();
  let held: TaskManagerDelta[] = [];
  let resyncTimer: ReturnType<typeof setTimeout> | null = null;

  function paint(delta: TaskManagerDelta, lane: DeltaLane): boolean {
    if (!sequence.laneTakes(lane, delta)) return true;
    if (lane === 'lists') {
      if (delta.list_rows) hooks.setLists(delta.list_rows);
      return true;
    }
    if (lane === 'aggregate') {
      const groups = hooks.groups();
      if (!groups) return true;
      const applied = applyToGroups(groups, delta);
      if (applied.changed) hooks.setGroups(applied.value);
      return !applied.missing;
    }
    const body = hooks.body();
    if (!body) return true;
    const applied = applyToBody(body, delta, hooks.includeSwarm(body.list));
    if (applied.changed) hooks.setBody(applied.value, body);
    return !applied.missing;
  }

  function apply(delta: TaskManagerDelta): void {
    const lanes: DeltaLane[] = ['lists', 'aggregate', 'body'];
    if (!lanes.map((lane) => paint(delta, lane)).every(Boolean)) hooks.refresh();
    else for (const entry of delta.lists ?? []) hooks.doneTouched?.(entry.list);
  }

  return {
    receive(frame: unknown): void {
      const delta = deltaOf<TaskManagerDelta>(frame);
      if (!delta) return;
      const verdict = sequence.receive(delta);
      if (verdict === 'stale') return;
      if (verdict === 'gap') {
        hooks.refresh();
      } else if (delta.resync) {
        resyncTimer ??= setTimeout(() => {
          resyncTimer = null;
          hooks.refresh();
        }, Math.random() * RESYNC_JITTER_MS);
      } else if (hooks.writing()) {
        held.push(delta);
      } else {
        apply(delta);
      }
    },
    replay(lane: DeltaLane, marker: DeltaMarker): TaskManagerListRow[] | null {
      const newer = sequence.read(lane, marker);
      if (lane === 'lists') return newer.filter((d) => d.list_rows).pop()?.list_rows ?? null;
      if (!newer.map((delta) => paint(delta, lane)).every(Boolean)) hooks.refresh();
      return null;
    },
    settled(): void {
      if (!held.length || hooks.writing()) return;
      const waiting = held;
      held = [];
      waiting.forEach(apply);
    },
  };
}
