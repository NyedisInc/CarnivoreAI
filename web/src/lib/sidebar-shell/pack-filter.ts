/* and writes nothing */
import { HOST_OFF_FOLD_PREFIX } from '../drawer/store-keys';

export interface FilterMachine {
    install_id: string;
    is_self?: boolean;
    host_key?: string | null;
}

export function hostOffKey(installId: string): string {
    return HOST_OFF_FOLD_PREFIX + installId;
}

export function offMachineIds(folded: readonly string[]): Set<string> {
    return new Set(folded.filter((k) => k.indexOf(HOST_OFF_FOLD_PREFIX) === 0).map((k) => k.slice(HOST_OFF_FOLD_PREFIX.length)));
}

export function filterRowsByHost<T extends object>(rows: readonly T[], roster: readonly FilterMachine[], off: ReadonlySet<string>): T[] {
    if (!off.size) return rows as T[];
    const self = roster.find((m) => m.is_self);
    const hidden = new Set<string>();
    for (const m of roster) if (off.has(m.install_id) && m.host_key) hidden.add(m.host_key);
    const selfOff = !!self && off.has(self.install_id);
    return rows.filter((r) => {
        const key = (r as { host_key?: string | null }).host_key;
        if (!key || key === 'local') return !selfOff;
        return !hidden.has(key);
    });
}
