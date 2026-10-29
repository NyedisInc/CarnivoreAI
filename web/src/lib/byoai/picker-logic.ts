import type { Translate } from '../sessions/types';
import type { ModelInfo, RecentModel } from './api';
import { modelsFor } from './form-logic';

export interface PickItem {
    readonly id: string;
    readonly text: string;
    readonly name: string;
    readonly vendor: string;
    readonly detail: string;
    readonly flags: readonly string[];
    readonly preset?: string;
    readonly recentAt?: number;
    readonly rank?: number;
}

export type Entry =
    | { readonly kind: 'header'; readonly key: string; readonly title: string; readonly section: 'recent' | 'popular' | 'vendor' }
    | { readonly kind: 'option'; readonly item: PickItem }
    | { readonly kind: 'custom'; readonly id: string };

export const SECTION_CAP = 8;

export const termsOf = (query: string): string[] => query.toLowerCase().split(/\s+/).filter(Boolean);

export function matchesAll(item: PickItem, terms: readonly string[]): boolean {
    if (terms.length === 0) return true;
    const hay = `${item.id} ${item.text} ${item.name} ${item.vendor}`.toLowerCase();
    return terms.every((term) => hay.includes(term));
}

export function highlight(text: string, terms: readonly string[]): Array<{ text: string; hit: boolean }> {
    if (terms.length === 0 || text === '') return [{ text, hit: false }];
    const lower = text.toLowerCase();
    const marked = new Array<boolean>(text.length).fill(false);
    for (const term of terms) {
        for (let at = lower.indexOf(term); at !== -1; at = lower.indexOf(term, at + 1)) {
            for (let i = at; i < at + term.length; i += 1) marked[i] = true;
        }
    }
    const runs: Array<{ text: string; hit: boolean }> = [];
    for (let i = 0; i < text.length; i += 1) {
        const last = runs[runs.length - 1];
        if (last && last.hit === marked[i]) last.text += text[i];
        else runs.push({ text: text[i]!, hit: marked[i]! });
    }
    return runs;
}

export function formatTokens(n: number): string {
    if (n >= 1_000_000) return `${Math.round((n / 1_000_000) * 10) / 10}m`;
    if (n >= 1_000) return `${Math.round(n / 1_000)}k`;
    return String(n);
}

export const formatPrice = (n: number): string => (n === 0 ? '0' : n >= 10 ? String(Math.round(n)) : String(Math.round(n * 100) / 100));

export function modelItems(models: readonly ModelInfo[], capability: string, recent: readonly RecentModel[],
    facts: (m: ModelInfo) => string): PickItem[] {
    const recentAt = new Map<string, number>();
    for (const r of recent) if (r.capability === capability && !recentAt.has(r.model)) recentAt.set(r.model, recentAt.size);
    const items: PickItem[] = modelsFor(models, capability).map((m) => {
        const slash = m.id.indexOf('/');
        const rank = m.meta['popular_rank'];
        const at = recentAt.get(m.id);
        return {
            id: m.id, text: m.id, name: m.label, vendor: slash > 0 ? m.id.slice(0, slash).replace(/^~/, '').replace(/^models$/, 'google') : '',
            detail: facts(m), flags: m.flags,
            ...(at !== undefined ? { recentAt: at } : {}),
            ...(typeof rank === 'number' ? { rank } : {}),
        };
    });
    const have = new Set(items.map((i) => i.id));
    for (const [model, at] of recentAt) {
        if (!have.has(model)) items.push({ id: model, text: model, name: '', vendor: '', detail: '', flags: [], recentAt: at });
    }
    return items;
}

export function buildEntries(items: readonly PickItem[], query: string, titles: { recent: string; popular: string },
    opts: { grouped: boolean; custom: boolean; alpha: boolean }): Entry[] {
    const terms = termsOf(query);
    const hits = items.filter((i) => matchesAll(i, terms));
    const entries: Entry[] = [];
    if (!opts.grouped) {
        for (const item of hits) entries.push({ kind: 'option', item });
    } else {
        const used = new Set<string>();
        const take = (list: PickItem[]): PickItem[] => { list.forEach((i) => used.add(i.id)); return list; };
        const recent = take(hits.filter((i) => i.recentAt !== undefined).sort((a, b) => a.recentAt! - b.recentAt!).slice(0, SECTION_CAP));
        const popular = take(hits.filter((i) => i.rank !== undefined && !used.has(i.id)).sort((a, b) => a.rank! - b.rank!).slice(0, SECTION_CAP));
        if (recent.length) entries.push({ kind: 'header', key: 'recent', title: titles.recent, section: 'recent' }, ...recent.map((item) => ({ kind: 'option' as const, item })));
        if (popular.length) entries.push({ kind: 'header', key: 'popular', title: titles.popular, section: 'popular' }, ...popular.map((item) => ({ kind: 'option' as const, item })));
        const open = hits.filter((i) => !used.has(i.id));
        const firstSeen = new Map<string, number>();
        for (const i of open) if (!firstSeen.has(i.vendor)) firstSeen.set(i.vendor, firstSeen.size);
        const rest = opts.alpha
            ? open.sort((a, b) => (a.vendor.localeCompare(b.vendor) || a.id.localeCompare(b.id)))
            : open.sort((a, b) => firstSeen.get(a.vendor)! - firstSeen.get(b.vendor)!);
        let vendor: string | null = null;
        for (const item of rest) {
            if (item.vendor !== vendor) {
                vendor = item.vendor;
                if (vendor !== '' || entries.length > 0) entries.push({ kind: 'header', key: `vendor:${vendor}`, title: vendor, section: 'vendor' });
            }
            entries.push({ kind: 'option', item });
        }
    }
    const typed = query.trim();
    if (opts.custom && typed !== '' && !items.some((i) => i.id.toLowerCase() === typed.toLowerCase())) entries.push({ kind: 'custom', id: typed });
    return entries;
}

export function modelFacts(m: ModelInfo, t: Translate): string {
    const parts: string[] = [];
    if (m.context_length) parts.push(t('settings.ai.picker.ctx', { n: formatTokens(m.context_length) }));
    if (m.price_in === 0 && m.price_out === 0) parts.push(t('settings.ai.picker.free'));
    else if (typeof m.price_in === 'number' && typeof m.price_out === 'number') {
        parts.push(t('settings.ai.picker.price', { input: formatPrice(m.price_in), output: formatPrice(m.price_out) }));
    }
    return parts.join(' · ');
}

export function defaultModelId(items: readonly PickItem[]): string {
    const by = (key: 'recentAt' | 'rank'): PickItem | undefined =>
        items.filter((i) => i[key] !== undefined).sort((a, b) => a[key]! - b[key]!)[0];
    return (by('recentAt') ?? by('rank') ?? items[0])?.id ?? '';
}

export function panelWidth(boxWidth: number, items: readonly PickItem[], viewport: number): number {
    const longest = items.reduce((n, i) => Math.max(n, i.text.length, i.detail.length + (i.name ? i.name.length + 3 : 0)), 0);
    const want = Math.max(boxWidth, 360, Math.ceil(longest * 7.5) + 96);
    return Math.max(0, Math.min(want, 768, viewport - 16));
}
