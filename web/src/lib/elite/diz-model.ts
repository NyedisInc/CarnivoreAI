import { ELITE_KEYS as K } from '../../../../client/js/labels/warez-elite.js';
import type { CardView } from '../catalog/card';
import { compatView } from '../catalog/compat';
import type { RatingsView } from '../catalog/ratings';
import type { CatalogItem, InstalledItem } from '../catalog/types';
import type { Translate } from '../sessions/types';
import { pad, sizeText } from './file-rows';

export const TRUST_CELLS = 20;
export const GRADE_CELLS = 10;
export const VERSION_ROWS = 3;

const GRADE_FRAC: Readonly<Record<string, number>> = { 'A+': 1, A: 1, 'A-': 0.9, 'B+': 0.8, B: 0.7, 'B-': 0.6, 'C+': 0.5, C: 0.4, 'C-': 0.3, D: 0.2, F: 0.1 };

export interface Meter {
    on: number;
    off: number;
}

export interface DizActions {
    kind: 'add' | 'update' | 'reinstall';
    addLabel: string;
    addOffline: boolean;
    tryLabel: string;
    tryable: boolean;
}

export interface DizModel {
    id: string;
    name: string;
    byLine: string;
    kind: string | null;
    kindTag: string;
    verdict: string;
    verdictTag: string;
    stateKind: 'upd' | 'inst' | 'avail';
    stateText: string;
    rating: { stars: string; text: string } | null;
    actions: DizActions;
    dl: string | null;
    brief: string;
    link: string;
    versionsHead: string;
    versions: { line: string; mark: string }[];
    works: string;
    swatches: string[];
    trust: Meter;
    trustWord: string;
    trustWhy: string;
    grade: Meter;
    gradeWord: string;
    live: string;
}

export interface DizInput {
    item: CatalogItem;
    card: CardView;
    held: readonly InstalledItem[];
    ratings: RatingsView | null;
    installs: number | null;
    offline: boolean;
    origin: string;
    palette: readonly string[] | null;
}

export function gradeFrac(letter: string | null): number {
    return letter ? (GRADE_FRAC[letter] ?? 0.5) : 0;
}

export function trustFrac(verdict: string, letter: string | null): number {
    if (verdict === 'clean') return letter ? gradeFrac(letter) : 0.5;
    if (verdict === 'flagged') return 0.5;
    if (verdict === 'blocked') return 0.1;
    return 0;
}

function meter(frac: number, n: number): Meter {
    const on = Math.round(Math.max(0, Math.min(1, frac)) * n);
    return { on, off: n - on };
}

export function starsText(avg: number): string {
    const f = Math.max(0, Math.min(5, Math.round(avg)));
    return '★'.repeat(f) + '☆'.repeat(5 - f);
}

export function dateText(iso: string | null | undefined): string {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '');
    return m ? `${m[2]}/${m[3]}/${m[1]!.slice(2)}` : '';
}

export function countWord(n: number): string {
    return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n);
}

export function versionsOf(item: CatalogItem): NonNullable<CatalogItem['versions']> {
    const all = [...(item.versions ?? [])].filter((v) => v && typeof v === 'object');
    const rank = (v: (typeof all)[number]): string => `${v.v === item.latest ? '1' : '0'}${v.published_at ?? ''}`;
    return all.sort((a, b) => (rank(a) < rank(b) ? 1 : rank(a) > rank(b) ? -1 : 0)).slice(0, VERSION_ROWS);
}

export function dizModel(input: DizInput, t: Translate): DizModel {
    const { item, card, held, ratings, installs, offline } = input;
    const id = card.id ?? '';
    const verdict = card.verdict ?? 'unreviewed';
    const updating = held.find((r) => r.update_available === true) ?? null;
    const stateKind = updating ? 'upd' : held.length ? 'inst' : 'avail';
    const stateText = updating
        ? t(K.dizStateUpdate, { from: updating.version ?? '', to: card.version ?? '' })
        : held.length
          ? t(K.dizStateInstalled, { version: held[0]!.version ?? '' })
          : t(K.dizStateAvailable);
    const kindWord = t(`warez.elite.kind.${card.kind}`);
    const kindTag = `[${kindWord.startsWith('warez.elite.') ? (card.kind ?? '').slice(0, 3).toUpperCase() : kindWord}]`;
    const verdictWord = t(`warez.elite.verdict.${verdict}`);
    const kind: DizActions['kind'] = updating ? 'update' : held.length ? 'reinstall' : 'add';
    const gradeLetter = card.gradeShape === 'graded' ? card.gradeLetter : null;
    const frac = trustFrac(verdict, gradeLetter);
    const compat = compatView(item);
    const author = card.author ?? card.publisher ?? id.split('/')[0] ?? '';
    const rows = versionsOf(item).map((v, i) => ({
        line: pad(v.v ?? '', 7) + pad(sizeText(Number(v.size ?? 0) || 0), 6, true) + pad(String(v.files ?? ''), 6, true) + pad(String(v.scripts ?? ''), 4, true) + ' ' + dateText(v.published_at),
        mark: i === 0 ? (updating ? t(K.markUpd) : held.length ? t(K.markInst) : '') : '',
    }));
    const why = card.reviewSummary || t(`warez.elite.diz.why.${verdict}`);
    let rating: DizModel['rating'] = null;
    if (ratings && ratings.shape === 'none') rating = { stars: '', text: t(K.dizRatingNone) };
    else if (ratings && ratings.shape === 'rated' && ratings.average !== null && ratings.count !== null) {
        const avg = ratings.average.toFixed(1);
        rating = { stars: starsText(ratings.average), text: t(K.dizRating, { avg, n: ratings.count, count: ratings.count }) };
    }
    const head = t(K.dizVersionsHead).split(' ');
    return {
        id,
        name: card.headline ?? id,
        byLine: t(K.dizBy, { author }),
        kind: card.kind,
        kindTag,
        verdict,
        verdictTag: `[${verdictWord}]`,
        stateKind,
        stateText,
        rating,
        actions: {
            kind,
            addLabel: offline ? t(K.dizAddOffline) : t(kind === 'update' ? K.dizUpdate : kind === 'reinstall' ? K.dizReinstall : K.dizAdd),
            addOffline: offline,
            tryLabel: t(card.untrusted ? K.dizTryNa : K.dizTry),
            tryable: !card.untrusted,
        },
        dl: installs === null ? null : t(K.dizDl, { n: countWord(installs) }),
        brief: String(item.fm?.description ?? '').trim() || card.brief || t(K.dizNoDesc),
        link: `${input.origin}/#warez/${id.split('/').map(encodeURIComponent).join('/')}`,
        versionsHead: pad(head[0] ?? '', 7) + pad(head[1] ?? '', 6, true) + pad(head[2] ?? '', 6, true) + pad(head[3] ?? '', 4, true) + ' ' + (head[4] ?? ''),
        versions: rows,
        works: [...compat.harnesses, ...compat.tools].join(', ') || t(K.dizWorksNone),
        swatches: input.palette ? [...input.palette] : [],
        trust: meter(frac, TRUST_CELLS),
        trustWord: verdictWord,
        trustWhy: why,
        grade: meter(gradeLetter ? gradeFrac(gradeLetter) : 0, GRADE_CELLS),
        gradeWord: gradeLetter ? t(K.dizGrade, { grade: gradeLetter }) : t(K.dizNoGrade),
        live: t(K.liveFile, { name: card.headline ?? id, kind: kindWord, version: card.version ?? '', verdict: verdictWord }),
    };
}
