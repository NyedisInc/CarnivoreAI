import { gradeView, type GradeShape } from './grade';
import { reviewView, type ReviewVerdict } from './review';
import { costView } from './cost';
import { displayKind } from './kind-display';
import type { CatalogItem, CatalogVersion } from './types';

export const MAX_TAGS = 8;
export const MAX_TAG_CHARS = 32;
export const MAX_HEADLINE_CHARS = 120;
export const MAX_BRIEF_CHARS = 280;
export const MAX_ICON_CHARS = 40;
export const MAX_SUMMARY_CHARS = 1000;
export const MAX_NAME_CHARS = 120;
export const MAX_PUBLISHER_CHARS = 120;
export const MAX_VERSION_CHARS = 64;

const CLIP_MARK = '...';

export interface CardView {
    renderKey: string;
    id: string | null;
    name: string | null;
    headline: string | null;
    brief: string | null;
    publisher: string | null;
    version: string | null;
    icon: string | null;
    mediaSha: string | null;
    tags: string[] | null;
    scripts: number | null;
    marksScripts: boolean;
    marksInstructionsWrite: boolean;
    instructionsDetails: string[];
    instructionsMore: number;
    reviewStatus: 'reviewed' | 'unavailable' | null;
    reviewSummary: string | null;
    warnings: number | null;
    flagged: boolean;
    verdict: ReviewVerdict | null;
    kind: string | null;
    indexKind: string | null;
    isTheme: boolean;
    isPlugin: boolean;
    isLoadout: boolean;
    isMod: boolean;
    isCplug: boolean;
    descTokens: number | null;
    untrusted: boolean;
    deprecated: boolean;
    supersededBy: string | null;
    gradeShape: GradeShape;
    gradeLetter: string | null;
    author: string | null;
    credit: { sourceUrl: string | null; publisher: string | null } | null;
}

function present<T>(value: T | null | undefined): T | null {
    return value !== undefined ? (value as T | null) : null;
}

function text(value: unknown): string | null {
    if (typeof value !== 'string') return null;
    const trimmed = value.trim();
    return trimmed ? trimmed : null;
}

function clip(value: string | null, limit: number): string | null {
    if (value === null) return null;
    const points = Array.from(value);
    if (points.length <= limit) return value;
    return points.slice(0, limit - CLIP_MARK.length).join('') + CLIP_MARK;
}

function firstWebUrl(candidates: readonly unknown[]): string | null {
    for (const c of candidates) {
        const v = text(c);
        if (v && /^https?:\/\//i.test(v)) return v;
    }
    return null;
}

function shown(value: unknown, limit: number): string | null {
    return clip(text(value), limit);
}

function mediaSha(media: unknown): string | null {
    const sha = media && typeof media === 'object' ? (media as { sha256?: unknown }).sha256 : null;
    return typeof sha === 'string' && /^[0-9a-f]{64}$/.test(sha) ? sha : null;
}

function tagList(raw: unknown): string[] | null {
    if (!Array.isArray(raw)) return null;
    const tags: string[] = [];
    const seen = new Set<string>();
    for (const entry of raw) {
        const tag = shown(entry, MAX_TAG_CHARS);
        if (!tag || seen.has(tag)) continue;
        seen.add(tag);
        tags.push(tag);
        if (tags.length >= MAX_TAGS) break;
    }
    return tags;
}

export function latestVersion(item: CatalogItem | null): CatalogVersion | null {
    if (!item) return null;
    const wanted = text(item.latest);
    if (!wanted) return null;
    const versions = Array.isArray(item.versions) ? item.versions : null;
    if (!versions) return null;
    for (const version of versions) {
        if (version && text(version.v) === wanted) return version;
    }
    return null;
}

export function cardView(item: CatalogItem | null, untrusted: boolean, index = 0): CardView {
    const version = latestVersion(item);
    const card = (item && item.card) || null;
    const review = (version && version.review) || null;
    const id = text(item && item.id);
    const name = shown(item && item.name, MAX_NAME_CHARS);
    const title = shown(card && card.title, MAX_HEADLINE_CHARS);
    const scripts = present(version ? version.scripts : undefined);
    const warnings = review && Array.isArray(review.warnings) ? review.warnings.length : null;
    const status = review ? present(review.status) : null;
    const reviewed = reviewView(review);
    const verdict = reviewed.overridden ? null : reviewed.verdict;
    const kind = text(item && item.kind);
    const shownKind = displayKind(kind);
    const fm: Record<string, unknown> = kind === 'plugin' && item && item.fm && typeof item.fm === 'object' ? item.fm : {};
    const author = shown(fm.author, MAX_PUBLISHER_CHARS);
    const publisher = shown(item && item.publisher, MAX_PUBLISHER_CHARS);
    const grade = gradeView(version && version.grade);
    return {
        renderKey: id ?? `#${index}`,
        id,
        name,
        headline: clip(title || name || id, MAX_HEADLINE_CHARS),
        brief: shown(card && card.brief, MAX_BRIEF_CHARS),
        publisher,
        version: shown(item && item.latest, MAX_VERSION_CHARS),
        icon: shown(card && card.icon, MAX_ICON_CHARS),
        mediaSha: mediaSha(card && card.media),
        tags: tagList(card && card.tags),
        scripts,
        marksScripts: typeof scripts === 'number' && scripts > 0,
        marksInstructionsWrite: reviewed.writesInstructions,
        instructionsDetails: reviewed.instructionsDetails,
        instructionsMore: reviewed.instructionsMore,
        reviewStatus: status === 'reviewed' || status === 'unavailable' ? status : null,
        reviewSummary: shown(review && review.summary, MAX_SUMMARY_CHARS),
        warnings,
        flagged: verdict === 'flagged' || verdict === 'blocked' || verdict === 'unreadable',
        verdict,
        kind: shownKind,
        indexKind: kind,
        isTheme: kind === 'theme',
        isPlugin: kind === 'plugin',
        isLoadout: kind === 'loadout',
        isMod: kind === 'mod',
        isCplug: kind === 'cplug',
        descTokens: costView(item)?.desc ?? null,
        untrusted,
        deprecated: !!(item && item.deprecated && typeof item.deprecated === 'object'),
        supersededBy: shown(item && item.deprecated && item.deprecated.superseded_by, MAX_NAME_CHARS + 40),
        gradeShape: grade.shape,
        gradeLetter: grade.letter,
        author,
        credit: author ? { sourceUrl: firstWebUrl([fm.homepage, fm.repository, fm.author_url]), publisher } : null,
    };
}

export function cardViews(items: CatalogItem[] | null, untrusted: boolean): CardView[] {
    const cards: CardView[] = [];
    const taken = new Set<string>();
    const list = Array.isArray(items) ? items : [];
    list.forEach((item, index) => {
        const card = cardView(item, untrusted, index);
        let key = card.renderKey;
        while (taken.has(key)) key += `#${index}`;
        taken.add(key);
        card.renderKey = key;
        cards.push(card);
    });
    return cards;
}

const KIND_ICONS: Readonly<Record<string, string>> = {
    skill: 'skill',
    theme: 'palette',
    plugin: 'plug',
    mod: 'mod',
    loadout: 'pack',
};

export function kindIcon(kind: string | null): string | null {
    return kind && Object.hasOwn(KIND_ICONS, kind) ? (KIND_ICONS[kind] ?? null) : null;
}
