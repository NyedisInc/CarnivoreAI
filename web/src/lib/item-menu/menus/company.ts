/**
 * A COMPANY heading's menu, declared once (issue #1338; wrapper package S-6): rename, color (the shared swatch row, plus clear
 * when it has one), delete alone and last in the destructive token. The orphaned-projects heading draws no kebab, so nothing
 * here reaches it; a key naming no company the store holds builds no menu. The writes are `sidebar-shell/company-actions.ts`'s
 * and `heading-color-actions.ts`'s.
 */
import { t } from '../../i18n/index.svelte';
import { companyById, setCompanyColor } from '../../companies';
import { deleteCompanyConfirm, renameCompanyPrompt } from '../../sidebar-shell/company-actions';
import { announceFailure, reasonOf } from '../../sidebar-shell/interaction-globals';
import { entryNodes, spaced } from '../entries';
import { defineItemMenu } from '../registry';
import { companyColorEntry } from './color';

defineItemMenu('company', {
    build({ key }, env) {
        const company = companyById(Number(key.slice(2)));
        if (!company) return null;
        const entries = spaced([
            [
                { label: t('sidebar.heading.rename'), icon: 'rename', id: 'rename-company', onPick: () => { void renameCompanyPrompt(company); } },
                companyColorEntry(company),
                ...(typeof company.hue === 'number' ? [{
                    label: t('sidebar.color.clear'), icon: 'close', id: 'clear-company-color',
                    onPick: () => { setCompanyColor(company.id, null).catch((err: unknown) => announceFailure(t('sidebar.color.failed', { name: company.name, reason: reasonOf(err) }))); },
                }] : []),
            ],
            [{ label: t('sidebar.company.menu.delete'), icon: 'close', id: 'delete-company', danger: true, onPick: () => { void deleteCompanyConfirm(company); } }],
        ]);
        return { nodes: entryNodes(entries, env.glyph, env.close), ariaLabel: t('sidebar.company.menu.title', { name: company.name }) };
    },
});
