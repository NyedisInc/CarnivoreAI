import type { MenuNode } from '../drawer-tabs/add-component-menu';
import { assignMenuKeys } from '../menu-keys/menu-keys';

export interface GoldenEntry {
    id: string;
    label: string;
    key: string;
    disabled?: string;
    sep?: true;
    danger?: true;
    tone?: 'update';
    locked?: true;
    checked?: boolean;
    toggle?: true;
    swatches?: true;
    children?: GoldenEntry[];
}

/* label: ' */
export function goldenOfNodes(nodes: readonly MenuNode[], shallow = false): GoldenEntry[] {
    const keys = assignMenuKeys(nodes.map((n) => ({ id: n.id, label: n.label, skip: !!n.blocked || !!n.swatches })));
    return nodes.map((n, i) => {
        const out: GoldenEntry = { id: n.id, label: n.label, key: keys[i] ?? '' };
        if (n.blocked) out.disabled = n.blocked;
        if (n.sep) out.sep = true;
        if (n.danger) out.danger = true;
        if ((n as MenuNode & { tone?: string }).tone === 'update') out.tone = 'update';
        if (n.locked) out.locked = true;
        if (n.checked !== undefined) out.checked = n.checked;
        if (n.toggle) out.toggle = true;
        if (n.swatches) out.swatches = true;
        if (n.children) out.children = shallow ? [] : goldenOfNodes(n.children);
        return out;
    });
}

export interface LegacyRowItem {
    id: string;
    label: string;
    shortcut: string;
    enabled: boolean;
    reason: string;
    separatorBefore: boolean;
    itemClass?: string;
    locked?: boolean;
}

export function goldenOfLegacyRow(items: readonly LegacyRowItem[], isBranch: (id: string) => boolean): GoldenEntry[] {
    return items.map((it) => {
        const out: GoldenEntry = { id: it.id, label: it.label, key: it.shortcut || '' };
        if (!it.enabled) out.disabled = it.reason;
        if (it.separatorBefore) out.sep = true;
        if (it.itemClass && /--update\b/.test(it.itemClass)) out.tone = 'update';
        if (it.locked) out.locked = true;
        if (isBranch(it.id)) out.children = [];
        return out;
    });
}
