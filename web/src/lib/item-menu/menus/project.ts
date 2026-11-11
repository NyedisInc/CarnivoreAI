import { t } from '../../i18n/index.svelte';
import { companyList } from '../../companies';
import { companySource } from '../../sidebar-shell/company-source.svelte';
import { agentOffered } from '../../projects-shared/agent-offer';
import { projectPanels } from '../../../cplugs/sdk/project-panels';
import { projectNameFor, setProjectColor } from '../../sidebar-shell/heading-project-actions';
import { drawerProjectOf, runDrawerProjectVerb } from '../../sidebar-shell/project-menu-run.svelte';
import { projectColorOf } from '../../project-colors/store.svelte';
import { setProjectColorPreview } from '../../project-colors/preview.svelte';
import { entryNodes } from '../entries';
import { defineItemMenu } from '../registry';
import { projectMenuEntries } from './project-entries';

defineItemMenu('project', {
    build({ key }, env) {
        const rawName = projectNameFor(key);
        const name = rawName || t('sidebar.project.unnamed');
        const label = t('sidebar.project.menu.title', { name });
        const id = Number(key.slice(2));
        const base = drawerProjectOf(key) ?? { id, name: rawName ?? '', archived_at: null };
        const project = { ...base, company_id: companySource().companyOf(String(id)) };
        const entries = projectMenuEntries({
            project,
            companies: companyList(),
            agentOffered: agentOffered(project),
            panels: projectPanels(),
            color: { value: projectColorOf(id) ?? '', onPick: (color) => { void setProjectColor(project.name, color, id); }, onPreview: (hex) => setProjectColorPreview(id, hex) },
            close: env.close,
            glyph: env.glyph,
            run: (verb) => runDrawerProjectVerb(key, verb),
        });
        return { nodes: entryNodes(entries, env.glyph, env.close), ariaLabel: label };
    },
});
