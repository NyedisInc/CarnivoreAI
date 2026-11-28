import { t } from '../../i18n/index.svelte';
import { newBrowser } from '../../browser/screen-host';
import { BAND_BROWSERS, BAND_FILES, BAND_TERMINALS } from '../../drawer/bucketing';
import { COMPANIES_FOLD_KEY, GROUPS_FOLD_KEY, LAYOUT_FOLD_KEY, ROGUE_FOLD_KEY } from '../../drawer/store-keys';
import { layoutEditor, toggleLayoutEditor } from '../../../opscenter/layout-editor/editor.svelte';
import { canOpen } from '../../../opscenter/layout-editor/empty-space-menu.svelte';
import { isBandFolded, toggleBandFold } from '../../sidebar-shell/heading-fold';
import { newCompanyPrompt } from '../../sidebar-shell/company-actions';
import { createGroupThenAssign } from '../../sidebar-shell/group-assign';
import { canStepSection, stepSectionBy } from '../../sidebar-shell/section-drag';
import { sectionIdOfKey } from '../../sidebar-shell/section-heading';
import { entryNodes, spaced, type ItemMenuEntry } from '../entries';
import { defineItemMenu } from '../registry';
import { foldInsideEntry } from './fold-inside';

const GROUP_HOST_SECTIONS = new Set<string>(['pinned', LAYOUT_FOLD_KEY, GROUPS_FOLD_KEY, ROGUE_FOLD_KEY, BAND_TERMINALS, BAND_BROWSERS, BAND_FILES]);

function headingName(row: Element): string {
    const toggle = row.querySelector('[data-group-toggle]');
    return row.querySelector('.session-sidebar-group__label')?.textContent?.trim() || toggle?.getAttribute('data-group-toggle') || '';
}

function editLayoutEntry(): ItemMenuEntry | null {
    if (!canOpen()) return null;
    const editing = layoutEditor.active;
    return {
        label: t(editing ? 'widgets.menu.done_editing' : 'widgets.menu.edit_layout'),
        icon: 'layout',
        id: editing ? 'done-editing' : 'edit-layout',
        onPick: () => { void toggleLayoutEditor(); },
    };
}

defineItemMenu('section', {
    build({ key, anchor }, env) {
        const id = sectionIdOfKey(key);
        if (!id) return null;
        const name = headingName(anchor);
        const entries = spaced([
            [{ label: t(isBandFolded(key) ? 'sidebar.section.menu.unfold' : 'sidebar.section.menu.fold'), icon: 'fold', id: 'fold', onPick: () => { toggleBandFold(key); } }],
            [foldInsideEntry(key)],
            [
                {
                    label: t('sidebar.section.menu.move_up'), icon: 'move-up', id: 'move-up',
                    ...(canStepSection(id, -1) ? {} : { blocked: t('widgets.menu.already_first') }),
                    onPick: () => { stepSectionBy(id, -1, key); },
                },
                {
                    label: t('sidebar.section.menu.move_down'), icon: 'move-down', id: 'move-down',
                    ...(canStepSection(id, 1) ? {} : { blocked: t('widgets.menu.already_last') }),
                    onPick: () => { stepSectionBy(id, 1, key); },
                },
            ],
            key === BAND_BROWSERS ? [{ label: t('sidebar.section.menu.new_browser'), icon: 'browser', id: 'browser', onPick: () => { void newBrowser(); } }] : [],
            key === COMPANIES_FOLD_KEY ? [{ label: t('sidebar.company.new.leaf'), icon: 'add', id: 'new-company', onPick: () => { void newCompanyPrompt(null); } }] : [],
            GROUP_HOST_SECTIONS.has(key) ? [{ label: t('sidebar.group.menu.new'), icon: 'add', id: 'group', onPick: () => { void createGroupThenAssign(null, undefined, key === GROUPS_FOLD_KEY ? null : key); } }] : [],
            [editLayoutEntry()].filter((entry): entry is ItemMenuEntry => entry !== null),
        ]);
        return { nodes: entryNodes(entries, env.glyph, env.close), ariaLabel: t('sidebar.section.menu.label', { name }) };
    },
});
