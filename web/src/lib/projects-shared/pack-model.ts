import type { Translate } from '../sessions/types';

export interface PackStorage {
    readonly state: string;
    readonly logical_bytes?: number | null;
    readonly archive_bytes?: number | null;
    readonly file_count?: number | null;
    readonly packed_at?: string | null;
    readonly packed_in?: number | null;
    readonly last_error?: string | null;
    readonly progress?: { readonly phase: string; readonly percent: number | null } | null;
    readonly integrity?: { readonly status: string; readonly message: string; readonly full: boolean } | null;
}

export interface PackCheck {
    readonly id: string;
    readonly ok: boolean;
    readonly message: string;
}

export interface PackAnswer {
    readonly kind: 'pack' | 'unpack';
    readonly ok: boolean;
    readonly checks: readonly PackCheck[];
    readonly warnings: readonly string[];
    readonly sizes: {
        readonly logical_bytes?: number | null;
        readonly file_count?: number | null;
        readonly estimate_low?: number;
        readonly estimate_high?: number;
    };
    readonly repos: readonly { readonly path: string }[];
    readonly local_only: readonly string[];
    readonly fingerprint: string;
    readonly job: unknown;
}

export const PACK_BUSY: readonly string[] = ['packing', 'verifying', 'retiring', 'extracting', 'restoring'];

export const isPacked = (storage: PackStorage | null | undefined): boolean => storage?.state === 'packed';

export const isPackBusy = (storage: PackStorage | null | undefined): boolean => PACK_BUSY.includes(storage?.state ?? '');

export function sizeWord(bytes: number | null | undefined): string {
    if (typeof bytes !== 'number' || !Number.isFinite(bytes)) return '?';
    if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} gb`;
    if (bytes >= 1e6) return `${Math.round(bytes / 1e6)} mb`;
    return `${Math.max(1, Math.round(bytes / 1e3))} kb`;
}

export interface PackTag {
    readonly text: string;
    readonly warn: boolean;
    readonly title: string;
}

export function packTag(storage: PackStorage | null | undefined, t: Translate): PackTag | null {
    if (!storage) return null;
    if (isPackBusy(storage)) {
        const percent = storage.progress?.percent;
        const phase = storage.progress?.phase ?? storage.state;
        const text = typeof percent === 'number' ? t('projects.page.tag.pack_progress', { phase, percent }) : phase;
        return { text, warn: false, title: '' };
    }
    if (!isPacked(storage)) return storage.last_error ? { text: t('projects.page.tag.pack_failed'), warn: true, title: storage.last_error } : null;
    const integrity = storage.integrity;
    if (integrity && integrity.status !== 'ok') {
        return { text: t('projects.page.tag.archive_changed'), warn: true, title: integrity.message };
    }
    const size = sizeWord(storage.archive_bytes);
    if (storage.packed_in) return { text: t('projects.page.tag.packed_inside'), warn: false, title: '' };
    return { text: t('projects.page.tag.packed', { size }), warn: false, title: '' };
}

export const failedChecks = (answer: PackAnswer): string => answer.checks.filter((c) => !c.ok).map((c) => c.message).join('; ');

export const onlyNeedsLocalOnly = (answer: PackAnswer): boolean => {
    const failed = answer.checks.filter((c) => !c.ok).map((c) => c.id);
    return failed.length > 0 && failed.every((id) => id === 'git_local_only');
};

export function confirmText(name: string, answer: PackAnswer, t: Translate): { message: string; detail: string } {
    const sizes = answer.sizes;
    const lines: string[] = [];
    if (answer.kind === 'pack') {
        const mid = ((sizes.estimate_low ?? 0) + (sizes.estimate_high ?? 0)) / 2;
        lines.push(t('projects.page.pack.repos', { count: answer.repos.length }));
        if (answer.local_only.length) lines.push(t('projects.page.pack.only_copy', { repos: answer.local_only.join('; ') }));
        const message = t('projects.page.pack.message', {
            name, size: sizeWord(sizes.logical_bytes), files: sizes.file_count ?? 0, after: sizeWord(mid),
        });
        return { message, detail: [...lines, ...answer.warnings].join('\n') };
    }
    const message = t('projects.page.unpack.message', { name, size: sizeWord(sizes.logical_bytes), files: sizes.file_count ?? 0 });
    return { message, detail: answer.warnings.join('\n') };
}
