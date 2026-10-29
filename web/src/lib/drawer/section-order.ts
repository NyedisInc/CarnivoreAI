
import { PAGE_SECTION_SLOT, pageSectionMeta } from './page-sections';

export const SECTION_IDS = ['pinned', 'layouts', 'groups', 'companies', 'rogue', 'terminals', 'browsers', PAGE_SECTION_SLOT, 'pack'] as const;

export type SectionId = (typeof SECTION_IDS)[number];

export const DEFAULT_SECTION_ORDER: readonly SectionId[] = SECTION_IDS;

export function isSectionId(value: unknown): value is SectionId {
    return typeof value === 'string' && (SECTION_IDS as readonly string[]).indexOf(value) !== -1;
}

export function sectionOfBand(key: string): SectionId | null {
    if (key === 'groups') return 'groups';
    if (key === PAGE_SECTION_SLOT || pageSectionMeta(key) !== null) return PAGE_SECTION_SLOT;
    return key === 'pinned' || key === 'layouts' || key === 'rogue' || key === 'terminals' || key === 'browsers' ? key : null;
}

export function resolveSectionOrder(stored?: readonly string[] | null): SectionId[] {
    const out: SectionId[] = [];
    for (const id of Array.isArray(stored) ? stored : []) if (isSectionId(id) && out.indexOf(id) === -1) out.push(id);
    if (!out.length) return [...DEFAULT_SECTION_ORDER];
    DEFAULT_SECTION_ORDER.forEach((id, at) => {
        if (out.indexOf(id) !== -1) return;
        let pred = -1;
        for (let i = at - 1; i >= 0 && pred === -1; i -= 1) pred = out.indexOf(DEFAULT_SECTION_ORDER[i] as SectionId);
        out.splice(pred + 1, 0, id);
    });
    return out;
}

/*  hidden  */
export function moveSection(
    order: readonly SectionId[], id: SectionId, beforeId: SectionId | null, visible: readonly SectionId[],
): SectionId[] {
    const rest = order.filter((x) => x !== id);
    let at: number;
    if (beforeId === null) {
        const last = [...rest].reverse().find((x) => visible.indexOf(x) !== -1);
        if (last === undefined) return [...order];
        at = rest.indexOf(last) + 1;
    } else {
        if (beforeId === id || rest.indexOf(beforeId) === -1) return [...order];
        at = rest.indexOf(beforeId);
    }
    const next = [...rest.slice(0, at), id, ...rest.slice(at)];
    return next.every((x, i) => x === order[i]) ? [...order] : next;
}

export function stepSection(
    order: readonly SectionId[], visible: readonly SectionId[], id: SectionId, delta: number,
): SectionId[] | null {
    const shown = order.filter((x) => visible.indexOf(x) !== -1);
    const at = shown.indexOf(id);
    const to = at + (delta < 0 ? -1 : 1);
    if (at === -1 || to < 0 || to >= shown.length) return null;
    return moveSection(order, id, delta < 0 ? (shown[to] as SectionId) : (shown[to + 1] ?? null), shown);
}

let preview: SectionId[] | null = null;

export function setPreviewOrder(order: readonly SectionId[] | null): void {
    preview = order ? [...order] : null;
}

export function previewOrder(): SectionId[] | null {
    return preview;
}
