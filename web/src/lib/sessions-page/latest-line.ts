import type { Translate } from '../sessions/types';
import type { HistorySession } from '../projects-shared/history-api';
import type { LatestLine } from './sessions-data.svelte';

export interface LatestView {
    readonly kind: 'prompt' | 'none';
    readonly stamp: string;
    readonly text: string;
}

export function dateWord(iso: string | null | undefined): string {
    const at = iso ? new Date(iso) : null;
    if (!at || Number.isNaN(at.getTime())) return '';
    return at.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }).toLowerCase();
}

export function latestView(s: HistorySession, line: LatestLine | undefined, now: number, t: Translate): LatestView {
    const gone = s.state === 'asleep' && s.has_transcript === false;
    const prefix = gone ? `${t('sessions.page.latest.gone')} · ` : '';
    if (line?.text) {
        const sameDay = line.at ? new Date(line.at).toDateString() === new Date(now).toDateString() : false;
        const stamp = line.at ? (sameDay ? t('sessions.page.latest.today') : dateWord(line.at)) : '';
        const lead = line.kind === 'first_prompt' ? `${t('sessions.page.latest.began')}: ` : '';
        return { kind: 'prompt', stamp, text: `${prefix}${lead}${line.text}` };
    }
    return { kind: 'none', stamp: '', text: `${prefix}${t('sessions.page.latest.none')}` };
}
