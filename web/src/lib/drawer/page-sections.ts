
export interface PageSectionMeta {
    id: string;
    labelKey: string;
    icon: string;
}

export const PAGE_SECTION_SLOT = 'review';

export const DEFAULT_PAGE_SECTION_ICON = 'globe';

const registry = new Map<string, PageSectionMeta>();

export function registerPageSections(list: readonly PageSectionMeta[]): void {
    for (const meta of list) if (!registry.has(meta.id)) registry.set(meta.id, meta);
}

export function resetPageSections(): void {
    registry.clear();
}

export function pageSectionMeta(id: string): PageSectionMeta | null {
    return registry.get(id) ?? null;
}
