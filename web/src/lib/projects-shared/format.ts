import type { Translate } from '../sessions/types';
import { ageLabel } from './ledger-model';

export function ageFormatter(t: Translate, now: () => number): (iso: string | null) => string {
    return (iso) =>
        ageLabel(iso, now(), {
            minutes: (n) => t('projects.page.ago.minutes', { n }),
            hours: (n) => t('projects.page.ago.hours', { n }),
            days: (n) => t('projects.page.ago.days', { n }),
            date: (d) =>
                t('projects.page.ago.date', {
                    date: d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }).toLowerCase(),
                }),
        });
}

export function stampLabel(iso: string | null): string {
    const at = iso ? new Date(iso) : null;
    if (!at || Number.isNaN(at.getTime())) return '';
    const day = at.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }).toLowerCase();
    const hh = String(at.getHours()).padStart(2, '0');
    const mm = String(at.getMinutes()).padStart(2, '0');
    return `${day} ${hh}:${mm}`;
}
