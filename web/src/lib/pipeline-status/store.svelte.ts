import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import { fetchPipelineStatus, type Fetcher, type PipelineStatus } from './api';

export const PIPELINE_STATUS_POLL_MS = 10000;
export const PIPELINE_STATUS_TOPICS: readonly string[] = ['pipeline'];

export interface StatusHandle {
    status: Resource<PipelineStatus>;
    release(): void;
}

let shared: Resource<PipelineStatus> | null = null;
let refs = 0;

export function statusResource(fetcher?: Fetcher): Resource<PipelineStatus> {
    return resource<PipelineStatus>(() => fetchPipelineStatus(fetcher), {
        intervalMs: PIPELINE_STATUS_POLL_MS,
        topics: [...PIPELINE_STATUS_TOPICS],
        name: 'pipeline-status',
    });
}

export function acquireStatus(fetcher?: Fetcher): StatusHandle {
    if (fetcher) {
        const own = statusResource(fetcher);
        return { status: own, release: () => own.stop() };
    }
    if (shared === null) shared = statusResource();
    refs += 1;
    const held = shared;
    let released = false;
    return {
        status: held,
        release: () => {
            if (released) return;
            released = true;
            refs -= 1;
            if (refs <= 0 && shared === held) {
                held.stop();
                shared = null;
                refs = 0;
            }
        },
    };
}
