import type { ConnectionOption, Harness, ProfileRow } from './api';
import { blankForm, uniqueId, slugFromLabel, type FormState } from './form-model';
import raw from './example-profiles.json';

export interface Example {
    id: string;
    harness: Harness;
    needs: Harness | null;
    endpoint_preset: string | null;
    model: { mode: 'default' | 'fixed' | 'ask'; value: string | null };
    permissions: FormState['permissions'];
    flags: string[];
}

export const EXAMPLES: readonly Example[] = raw as Example[];

export function exampleForm(ex: Example, label: string, connections: readonly ConnectionOption[]): FormState {
    const found = ex.endpoint_preset ? connections.find((c) => c.preset === ex.endpoint_preset && c.enabled) : undefined;
    return {
        ...blankForm(), label, id: slugFromLabel(label), harness: ex.harness, permissions: ex.permissions,
        modelMode: ex.model.mode, modelValue: ex.model.value ?? '', flagsText: ex.flags.join('\n'),
        endpointMode: ex.endpoint_preset ? 'connection' : 'native', connectionId: found?.id ?? '',
        shellProfile: ex.harness !== 'shell',
    };
}

export function offeredExamples(rows: readonly Pick<ProfileRow, 'harness' | 'installed'>[]): Example[] {
    const has = (h: Harness): boolean => rows.some((r) => r.harness === h && r.installed !== false);
    return EXAMPLES.filter((e) => e.endpoint_preset === null && (e.needs === null || has(e.needs)));
}

export function exampleId(label: string, taken: ReadonlySet<string>): string {
    return uniqueId(slugFromLabel(label), taken);
}
