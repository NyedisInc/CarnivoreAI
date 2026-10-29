import {
    ICON_REGISTRY,
    findIcon,
} from '../../../../client/js/icons/icon-registry.js';
import type { Translate } from '../sessions/types';

export interface PickableIcon {
    readonly id: string;
    readonly glyph: string;
    readonly label: string;
    readonly keywords: readonly string[];
}

export const PICKABLE_ICONS = ICON_REGISTRY as readonly PickableIcon[];

export const resolveIcon = findIcon as (id: unknown) => PickableIcon | null;

export const ICON_PICKER_KEYS = {
    label: 'icon_picker.label',
    searchLabel: 'icon_picker.search.label',
    searchPlaceholder: 'icon_picker.search.placeholder',
    none: 'icon_picker.none',
    empty: 'icon_picker.empty',
} as const;

export const PICKER_COLUMNS = 8;

export function iconValue(value: unknown): string | null {
    return typeof value === 'string' && value !== '' ? value : null;
}

export function filterIcons(query: string, t: Translate): readonly PickableIcon[] {
    const q = query.trim().toLowerCase();
    if (q === '') return PICKABLE_ICONS;
    return PICKABLE_ICONS.filter((icon) =>
        icon.id.includes(q)
        || t(icon.label).toLowerCase().includes(q)
        || icon.keywords.some((word) => word.includes(q)));
}

export function moveIndex(
    index: number,
    key: string,
    count: number,
    columns: number = PICKER_COLUMNS,
): number | null {
    if (count <= 0) return null;
    const last = count - 1;
    const clamp = (n: number): number => Math.min(Math.max(n, 0), last);
    switch (key) {
        case 'ArrowRight': return clamp(index + 1);
        case 'ArrowLeft': return clamp(index - 1);
        case 'ArrowDown': return index + columns <= last ? index + columns : index;
        case 'ArrowUp': return index - columns >= 0 ? index - columns : index;
        case 'Home': return 0;
        case 'End': return last;
        default: return null;
    }
}
