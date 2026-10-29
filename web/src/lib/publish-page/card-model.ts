import type { Translate } from '../sessions/types';
import type { SubRow } from './types';
import type { HeroOutcome } from './wizard-model';

export type HeroState = 'chosen' | 'made' | 'making' | 'failed' | 'waiting' | 'approved' | 'rejected' | 'none';
export type Picture = 'url' | 'art' | 'sent' | 'glyph';

export interface CardInput {
    drafting: boolean;
    draft: { url: string | null; own: boolean };
    outcome: HeroOutcome;
    send: { hero: string; sha?: string } | null;
    media: readonly SubRow[];
    kind: string;
}

export interface CardView {
    state: HeroState;
    picture: Picture;
    url: string | null;
    sha: string | null;
    source: string;
}

function reviewOf(row: SubRow): 'waiting' | 'approved' | 'rejected' {
    if (row.status === 'approved' || row.status === 'published') return 'approved';
    if (row.status === 'rejected' || row.status === 'revoked' || row.status === 'gate_failed') return 'rejected';
    return 'waiting';
}

export function cardOf(input: CardInput, t: Translate): CardView {
    const made = input.send?.hero === 'made';
    const line = (key: string, params?: Record<string, unknown>): string => t(key, params);
    if (input.drafting) {
        if (input.draft.own && input.draft.url) return { state: 'chosen', picture: 'url', url: input.draft.url, sha: null, source: line('publish.page.card.src_chosen_unsent') };
        return { state: 'none', picture: 'glyph', url: null, sha: null, source: line('publish.page.card.src_will_make') };
    }
    if (input.outcome === 'making') return { state: 'making', picture: 'glyph', url: null, sha: null, source: line('publish.page.card.src_generating') };
    if (input.outcome === 'failed') return { state: 'failed', picture: 'glyph', url: null, sha: null, source: line('publish.new.hero_failed') };
    const newest = input.media.filter((row) => row.status !== 'withdrawn').sort((a, b) => (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0))[0];
    const sha = !made && input.send?.sha ? input.send.sha : null;
    const picture: Picture = made ? 'art' : sha ? 'sent' : 'glyph';
    const own = line(made ? 'publish.new.hero_made' : 'publish.page.card.src_yours');
    if (newest) {
        const review = reviewOf(newest);
        if (review === 'rejected') return { state: 'rejected', picture: 'glyph', url: null, sha: null, source: line('publish.page.card.src_rejected', { reason: newest.reason || newest.revocation_reason }) };
        if (review === 'waiting') return { state: 'waiting', picture, url: null, sha, source: line('publish.page.card.src_waiting') };
        return { state: 'approved', picture, url: null, sha, source: own };
    }
    if (input.send?.hero) return { state: 'made', picture, url: null, sha, source: own };
    return { state: 'none', picture: 'glyph', url: null, sha: null, source: line('publish.page.card.src_none') };
}
