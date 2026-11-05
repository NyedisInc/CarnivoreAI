import { t } from '../i18n/index.svelte';
import type { BadgeItem } from './slot';

interface PrRecord {
    number?: number; url?: string; state?: string; ci?: string | null; review?: string | null; conflict?: boolean;
    unresolved?: number; stale?: boolean; hint?: string;
}

const TONE: Record<string, string | undefined> = { merged: 'good', closed: 'muted', draft: 'muted' };

export function prBadges(row: Record<string, unknown>): BadgeItem[] {
    const pr = row.pr as PrRecord | null | undefined;
    if (!pr || typeof pr !== 'object') return [];
    if (pr.hint === 'connect_gh') {
        return [{ kind: 'pr', key: 'hint', text: t('session.badges.pr.connect'), title: t('session.badges.pr.connect_title'), tone: 'muted' }];
    }
    if (!Number.isInteger(pr.number) || !pr.state) return [];
    const parts = [`#${pr.number}`, t(`session.badges.pr.state.${pr.state}`)];
    if (pr.ci === 'red') parts.push(t('session.badges.pr.ci_red'));
    if (pr.conflict) parts.push(t('session.badges.pr.conflict'));
    if (pr.unresolved) parts.push(t('session.badges.pr.unresolved', { count: String(pr.unresolved) }));
    const text = parts.join(' · ');
    const lines = [text, pr.ci === 'pending' ? t('session.badges.pr.ci_pending') : '', pr.ci === 'green' ? t('session.badges.pr.ci_green') : '',
        pr.review ? t(`session.badges.pr.review.${pr.review}`) : '', pr.stale ? t('session.badges.pr.stale') : '', t('session.badges.pr.open_hint')].filter(Boolean);
    const bad = pr.ci === 'red' || pr.conflict;
    const item: BadgeItem = { kind: 'pr', key: String(pr.number), text, title: lines.join('\n'), tone: bad ? 'bad' : TONE[pr.state] };
    const url = pr.url ?? '';
    if (url.startsWith('https://github.com/')) item.activate = () => { window.open(url, '_blank', 'noopener'); };
    return [item];
}
