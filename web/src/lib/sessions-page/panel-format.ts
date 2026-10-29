import { dateWord } from './latest-line';

export function whenWord(iso: string | null | undefined, now: number): string {
    const at = iso ? new Date(iso) : null;
    if (!at || Number.isNaN(at.getTime())) return '';
    if (at.toDateString() !== new Date(now).toDateString()) return dateWord(iso);
    return `${String(at.getHours()).padStart(2, '0')}:${String(at.getMinutes()).padStart(2, '0')}`;
}

export function homeWord(path: string | null | undefined): string {
    return (path ?? '').replace(/^\/Users\/[^/]+/, '~');
}
