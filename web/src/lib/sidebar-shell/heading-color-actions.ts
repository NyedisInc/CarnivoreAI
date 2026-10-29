import { t } from '../i18n/index.svelte';
import { setCompanyColor } from '../companies';
import { closeItemMenu, openItemMenu } from '../item-menu/open.svelte';
import { announceFailure, applyGroups, hg, reasonOf, usableGroups } from './interaction-globals';

export type ColorKind = 'company' | 'group' | 'layout';

export async function writeColor(kind: ColorKind, id: string, color: string, name: string): Promise<boolean> {
    closeItemMenu();
    try {
        if (kind === 'company') {
            await setCompanyColor(Number(id), color);
        } else if (kind === 'group') {
            const api = hg().API;
            const group = usableGroups()?.groupByUuid(id);
            if (!api || !group) throw new Error(t('sidebar.color.unavailable'));
            applyGroups(await api.setSessionGroupStyle(id, { colour: color, gradient: null, animation: group.animation || 'none' }));
        } else {
            const layouts = hg().CloudeWeb?.layouts;
            const layout = layouts?.get?.(id);
            if (!layouts?.setStyle || !layout) throw new Error(t('sidebar.color.unavailable'));
            await layouts.setStyle(id, { colour: color, gradient: null, animation: layout.animation || 'none' });
        }
        return true;
    } catch (err) {
        announceFailure(t('sidebar.color.failed', { name, reason: reasonOf(err) }));
        return false;
    }
}

export function currentColour(kind: 'group' | 'layout', id: string): { value: string; name: string } | null {
    if (kind === 'group') {
        const group = usableGroups()?.groupByUuid(id);
        return group ? { value: group.colour ?? '', name: group.name } : null;
    }
    const layout = hg().CloudeWeb?.layouts?.get?.(id);
    return layout ? { value: layout.colour ?? '', name: layout.name } : null;
}

export function openColorMenu(anchor: Element, kind: 'group' | 'layout', id: string): boolean {
    return openItemMenu('color', { kind, id, anchor }, anchor);
}
