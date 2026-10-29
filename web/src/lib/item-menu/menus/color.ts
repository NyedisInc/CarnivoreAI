import { t } from '../../i18n/index.svelte';
import type { Company } from '../../companies';
import { currentColour, writeColor } from '../../sidebar-shell/heading-color-actions';
import { hg } from '../../sidebar-shell/interaction-globals';
import { entryNodes, type ItemMenuEntry } from '../entries';
import { defineItemMenu } from '../registry';

export function companyColorEntry(company: Company): ItemMenuEntry {
    return {
        label: '', id: 'company-color', onPick: () => undefined,
        colors: { value: '', onPick: (color) => { void writeColor('company', String(company.id), color, company.name); } },
    };
}

defineItemMenu('color', {
    build({ kind, id, anchor }, env) {
        const current = currentColour(kind, id);
        if (!current) return null;
        const entries: ItemMenuEntry[] = [
            {
                label: '', id: `${kind}-color`, onPick: () => undefined,
                colors: { value: current.value, onPick: (color) => { void writeColor(kind, id, color, current.name); } },
            },
            {
                label: t('sidebar.color.more'), icon: 'colour', id: 'color-style', separatorBefore: true,
                onPick: () => { hg().SessionSidebarGroupColour?.openFull?.(anchor, kind, id); },
            },
        ];
        return { nodes: entryNodes(entries, env.glyph, env.close), ariaLabel: t('sidebar.color.title', { name: current.name }) };
    },
});
