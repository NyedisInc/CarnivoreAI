import type { GuideSection } from './guide-content';

export function filterSections(query: string, sections: readonly GuideSection[]): GuideSection[] {
    const needle = query.trim().toLowerCase();
    if (!needle) return [...sections];
    return sections.filter((s) => s.searchText.includes(needle));
}
