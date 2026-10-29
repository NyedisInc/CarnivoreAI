import type { MenuNode } from '../drawer-tabs/add-component-menu';
import { closing } from '../widget-menu/model';

export interface ItemMenuEntry {
    label: string;
    icon?: string;
    id?: string;
    separatorBefore?: boolean;
    colors?: { value: string; onPick: (key: string) => void; allowNone?: boolean; onPreview?: (hex: string | null) => void };
    children?: () => MenuNode[];
    blocked?: string;
    danger?: boolean;
    onPick(): void;
}

export function spaced(groups: ItemMenuEntry[][]): ItemMenuEntry[] {
    const out: ItemMenuEntry[] = [];
    for (const group of groups) {
        group.forEach((entry, i) => out.push(i === 0 && out.length ? { ...entry, separatorBefore: true } : entry));
    }
    return out;
}

/* label: ' */
export function entryNodes(entries: readonly ItemMenuEntry[], glyph: (icon: string | undefined) => string, close: () => void): MenuNode[] {
    const seen = new Map<string, number>();
    return entries.map((entry): MenuNode => {
        const base = entry.id ?? entry.icon ?? 'item';
        const count = seen.get(base) ?? 0;
        seen.set(base, count + 1);
        const id = count === 0 ? base : `${base}-${count}`;
        const sep = entry.separatorBefore ? true : undefined;
        if (entry.colors) {
            const colors = entry.colors;
            return { id, label: '', sep, swatches: { value: colors.value, allowNone: colors.allowNone === true, onPick: (key) => colors.onPick(key), onPreview: colors.onPreview } };
        }
        const html = glyph(entry.icon);
        const node: MenuNode = { id, label: entry.label, sep, ...(html ? { glyphHtml: html } : {}) };
        if (entry.danger) node.danger = true;
        if (entry.blocked) node.blocked = entry.blocked;
        if (entry.children) node.children = closing(entry.children(), close);
        else
            node.run = () => {
                close();
                entry.onPick();
            };
        return node;
    });
}
