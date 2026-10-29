import { resourcePush } from '../resource-push/boot';
import { LIVENESS } from '../resource-push/store';
import { errorCode, fetchSurface, type Surface, type SurfaceAnswer } from './api';

export const CPLUG_UI_FAMILY = 'cplug_ui';

export type SurfaceState =
    | { kind: 'loading' }
    | { kind: 'ready'; document: unknown; stale: boolean }
    | { kind: 'refused' }
    | { kind: 'stopped' }
    | { kind: 'none' };

export interface SurfaceSpec {
    readonly cplugId: string;
    /* could not */
    readonly installKey: string | null;
    readonly surface: Surface;
}

export function stateOf(answer: SurfaceAnswer): SurfaceState {
    return { kind: 'ready', document: answer.document, stale: answer.stale === true };
}

export function stateOfError(error: unknown): SurfaceState {
    const code = errorCode(error);
    if (code === 'cplug_not_running' || code === 'cplug_disabled') return { kind: 'stopped' };
    if (code === 'invalid_ui_document') return { kind: 'refused' };
    return { kind: 'none' };
}

export function watchSurface(spec: SurfaceSpec, set: (state: SurfaceState) => void, read: typeof fetchSurface = fetchSurface): () => void {
    let live = true;
    let seq = 0;
    const load = (): void => {
        const mine = ++seq;
        read(spec.cplugId, spec.surface).then(
            (answer) => { if (live && mine === seq) set(stateOf(answer)); },
            (error) => { if (live && mine === seq) set(stateOfError(error)); },
        );
    };
    load();
    const topic = spec.installKey ? `${CPLUG_UI_FAMILY}:${spec.installKey}` : null;
    const push = resourcePush();
    const off = push.onChange((topics) => {
        if (topic && push.isLive(topic) && (topics.includes(topic) || topics.includes(LIVENESS))) load();
    });
    return () => {
        live = false;
        off();
    };
}
