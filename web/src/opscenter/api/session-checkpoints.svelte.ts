import { authFetch } from './auth.svelte';
import { resource, type Resource } from './poll.svelte';
import { sharedResources } from './shared-resource';
import { CHECKPOINT_USAGE_TOPIC, checkpointsTopic, type CheckpointList, type CheckpointUsage } from '../../lib/checkpoints/api';

export const CHECKPOINTS_POLL_MS = 30000;

const reads = sharedResources<string, unknown>();

function hold<T>(key: string, path: string, topic: string): Resource<T> {
  return reads.hold(key, () => resource<unknown>(() => authFetch<T>(path), {
    intervalMs: CHECKPOINTS_POLL_MS,
    topics: [topic],
    name: `session-checkpoints:${key}`,
  })) as Resource<T>;
}

export function sessionCheckpoints(rowId: number): Resource<CheckpointList> {
  return hold<CheckpointList>(`s:${rowId}`, `/sessions/${rowId}/checkpoints`, checkpointsTopic(rowId));
}

export function releaseSessionCheckpoints(rowId: number): void {
  reads.drop(`s:${rowId}`);
}

export function checkpointUsage(): Resource<CheckpointUsage> {
  return hold<CheckpointUsage>('usage', '/checkpoints/usage', CHECKPOINT_USAGE_TOPIC);
}

export function releaseCheckpointUsage(): void {
  reads.drop('usage');
}
