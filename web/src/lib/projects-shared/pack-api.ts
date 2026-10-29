import { authFetch } from '../../opscenter/api/auth.svelte';
import type { PackAnswer } from './pack-model';

export interface PackApi {
    plan(kind: 'pack' | 'unpack', name: string, acceptLocalOnly: boolean): Promise<PackAnswer>;
    apply(kind: 'pack' | 'unpack', name: string, fingerprint: string, acceptLocalOnly: boolean): Promise<PackAnswer>;
}

const seg = (value: string): string => encodeURIComponent(value);

const post = (kind: 'pack' | 'unpack', name: string, body: Record<string, unknown>): Promise<PackAnswer> =>
    authFetch<PackAnswer>(`/projects/${seg(name)}/${kind}`, { method: 'POST', body: JSON.stringify(body) });

export const packApi: PackApi = {
    plan: (kind, name, acceptLocalOnly) => post(kind, name, kind === 'pack' ? { apply: false, accept_local_only: acceptLocalOnly } : { apply: false }),
    apply: (kind, name, fingerprint, acceptLocalOnly) =>
        post(kind, name, {
            apply: true,
            plan_fingerprint: fingerprint,
            ...(kind === 'pack' ? { accept_local_only: acceptLocalOnly } : {}),
        }),
};
