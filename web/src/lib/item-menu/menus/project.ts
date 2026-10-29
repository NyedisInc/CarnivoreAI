import { t } from '../../i18n/index.svelte';
import { addToNodes } from '../../add-to-menu/host';
import { companySource } from '../../sidebar-shell/company-source.svelte';
import { removeFromCompany } from '../../sidebar-shell/company-actions';
import {
    newAgentInProject, projectNameFor, removeProject, renameProject, setProjectColor, showProjectPath, sleepProject,
} from '../../sidebar-shell/heading-project-actions';
import { hg } from '../../sidebar-shell/interaction-globals';
import { projectColorOf } from '../../project-colors/store.svelte';
import { setProjectColorPreview } from '../../project-colors/preview.svelte';
import { entryNodes, spaced, type ItemMenuEntry } from '../entries';
import { defineItemMenu } from '../registry';

defineItemMenu('project', {
    build({ key }, env) {
        const rawName = projectNameFor(key);
        const name = rawName || t('sidebar.project.unnamed');
        const projectId = key.slice(2);
        const filed = rawName !== null && companySource().companyOf(projectId) !== null;
        const openGroup: ItemMenuEntry[] = [
            { label: t('opscenter.tabs.new_agent'), icon: 'agent', id: 'new-agent', onPick: () => { void newAgentInProject(key); } },
            { label: t('layout.row.load_blueprint'), icon: 'cube', id: 'load-blueprint', onPick: () => hg().CloudeWeb?.openBlueprintsScreen?.() },
        ];
        const identityGroup: ItemMenuEntry[] = [
            { label: t('sidebar.heading.rename'), icon: 'rename', id: 'rename-project', onPick: () => { renameProject(key); } },
        ];
        if (rawName) {
            identityGroup.push({ label: t('sidebar.project.add_to'), icon: 'add', id: 'add-to-company', children: () => addToNodes.forProject(rawName), onPick: () => undefined });
        }
        if (rawName && /^[0-9]+$/.test(projectId)) {
            identityGroup.push({
                label: '', id: 'project-color', onPick: () => undefined,
                colors: { value: projectColorOf(Number(projectId)) ?? '', allowNone: true, onPick: (color) => { void setProjectColor(rawName, color, Number(projectId)); }, onPreview: (hex) => setProjectColorPreview(Number(projectId), hex) },
            });
        }
        if (filed && rawName) {
            identityGroup.push({ label: t('sidebar.project.remove_from_company'), icon: 'move-up', id: 'remove-from-company', onPick: () => { void removeFromCompany(rawName); } });
        }
        const entries = spaced([
            openGroup,
            identityGroup,
            [{ label: t('sidebar.show_path.label'), icon: 'show-path', id: 'show-path', onPick: () => { void showProjectPath(key); } }],
            [{ label: t('sidebar.heading.sleep'), icon: 'sleep', id: 'sleep', onPick: () => { void sleepProject(key); } }],
            [{ label: t('sidebar.heading.remove'), icon: 'close', id: 'delete-project', danger: true, onPick: () => { void removeProject(key); } }],
        ]);
        return { nodes: entryNodes(entries, env.glyph, env.close), ariaLabel: t('sidebar.project.menu.title', { name }) };
    },
});
