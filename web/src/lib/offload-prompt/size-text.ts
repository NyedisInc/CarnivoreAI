import type { Translate } from '../sessions/types';

const KB = 1024;
const MB = KB * 1024;
const GB = MB * 1024;

export function sizeText(bytes: number, t: Translate): string {
    const one = (n: number): number => Math.round(n * 10) / 10;
    if (bytes >= GB) return t('offload.prompt.size.gb', { value: one(bytes / GB) });
    if (bytes >= MB) return t('offload.prompt.size.mb', { value: one(bytes / MB) });
    return t('offload.prompt.size.kb', { value: one(Math.max(0, bytes) / KB) });
}
