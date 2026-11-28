import type { Translate } from '../sdk';
import { gigabytes, megabytes } from './bytes';
import type { OffloadRow } from './offload-api';

const GB = 1024 ** 3;
const SHORT = 8;

export function sizeText(bytes: number, t: Translate): string {
    return bytes >= GB ? t('cplug.save.offload.size_gb', { value: gigabytes(bytes) }) : t('cplug.save.offload.size_mb', { value: megabytes(bytes) });
}

export function dayText(epochSeconds: number, locale?: string): string {
    if (!epochSeconds) return '';
    return new Date(epochSeconds * 1000).toLocaleDateString(locale, { day: 'numeric', month: 'short', year: 'numeric' }).toLowerCase();
}

export function nameText(row: OffloadRow, t: Translate): string {
    if (row.kind === 'conversation') return t('cplug.save.offload.conversation_name', { id: (row.conversation_id ?? '').slice(0, SHORT) });
    return row.title && row.title.trim() ? row.title : t('cplug.save.offload.session_name', { id: (row.session_uuid ?? '').slice(0, SHORT) });
}

const WHY_KEYS: Readonly<Record<string, string>> = {
    present_elsewhere: 'cplug.save.offload.why_present_elsewhere',
};

export function whyText(row: OffloadRow, t: Translate): string {
    const key = row.error_code ? WHY_KEYS[row.error_code] : undefined;
    return key ? t(key, { path: row.error_path ?? '' }) : row.error;
}

export function factsText(row: OffloadRow, t: Translate): string {
    const day = dayText(row.offloaded_at);
    const parts = [
        row.project ?? '',
        t(row.conversations === 1 ? 'cplug.save.offload.count_one' : 'cplug.save.offload.count_many', { count: row.conversations }),
        sizeText(row.bytes, t),
        day ? t('cplug.save.offload.when', { day }) : '',
    ];
    return parts.filter((p) => p !== '').join(', ');
}
