import { readCached, throttledWriter } from '../../lib/data-cache/cache';
import { isApproved, type HuddleItem, type TaskManagerGroup, type TaskManagerListBody } from './huddle-model';

export const TASK_MANAGER_CACHE_KEY = 'task-manager';

export const MAX_BODIES = 6;

export interface TaskManagerSnapshot {
    aggregate: TaskManagerGroup[] | null;
    bodies: Record<string, TaskManagerListBody>;
}

const latest: TaskManagerSnapshot = { aggregate: null, bodies: {} };
const writer = throttledWriter<TaskManagerSnapshot>(TASK_MANAGER_CACHE_KEY, () => latest);

function openItems(items: readonly HuddleItem[]): HuddleItem[] {
    return items.filter((item) => !item.placeholder && !isApproved(item.state));
}

export function saveTaskManagerSnapshot(kind: 'aggregate', value: readonly TaskManagerGroup[]): void;
export function saveTaskManagerSnapshot(kind: string, value: TaskManagerListBody): void;
export function saveTaskManagerSnapshot(kind: string, value: readonly TaskManagerGroup[] | TaskManagerListBody): void {
    if (kind === 'aggregate') {
        latest.aggregate = (value as readonly TaskManagerGroup[]).map((g) => ({ ...g, items: openItems(g.items) }));
    } else {
        const body = value as TaskManagerListBody;
        delete latest.bodies[kind];
        latest.bodies[kind] = { ...body, items: openItems(body.items) };
        for (const old of Object.keys(latest.bodies).slice(0, -MAX_BODIES)) delete latest.bodies[old];
    }
    writer.schedule();
}

export async function readTaskManagerSnapshot(): Promise<TaskManagerSnapshot | null> {
    const snap = await readCached<TaskManagerSnapshot>(TASK_MANAGER_CACHE_KEY);
    if (!snap || typeof snap !== 'object' || typeof snap.bodies !== 'object') return null;
    return snap;
}
