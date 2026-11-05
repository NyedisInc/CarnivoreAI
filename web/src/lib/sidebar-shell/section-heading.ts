import { isSectionId, sectionOfBand, type SectionId } from '../drawer/section-order';

const SECTION_ATTR = 'data-section';

const TOGGLE_ATTR = 'data-group-toggle';

export interface SectionTarget {
    key: string;
    row: Element;
}

export function sectionIdOfKey(key: string): SectionId | null {
    if (isSectionId(key)) return key;
    return sectionOfBand(key);
}

export function sectionTargetOf(row: Element): SectionTarget | null {
    const key = row.querySelector(`[${TOGGLE_ATTR}]`)?.getAttribute(TOGGLE_ATTR) ?? '';
    const parent = row.parentElement;
    const top = !!parent && parent.firstElementChild === row && parent.hasAttribute(SECTION_ATTR);
    return key && top && sectionIdOfKey(key) ? { key, row } : null;
}
