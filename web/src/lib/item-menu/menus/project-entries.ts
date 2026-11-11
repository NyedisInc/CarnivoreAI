import type { Company } from '../../companies';
import { t } from '../../i18n/index.svelte';
import { SET_COMPANY } from '../../projects-shared/ledger-model';
import { PROJECT_PANEL, PROJECT_SETTINGS } from '../../sessions-page/project-tools';
import { entryNodes, spaced, type ItemMenuEntry } from '../entries';
import type { MenuNode } from '../../drawer-tabs/add-component-menu';

export interface ProjectMenuProject {
    readonly id?: number | null;
    readonly name?: string;
    readonly archived_at: string | null;
    readonly root?: string | null;
    readonly company_id?: number | null;
    readonly storage?: { readonly state: string; readonly packed_in?: number | null } | null;
    readonly pack_state?: string | null;
    readonly new_sessions_join_swarm?: boolean;
}

export interface ProjectMenuInput {
    project: ProjectMenuProject;
    companies: readonly Company[];
    agentOffered: boolean;
    panels: readonly { readonly id: string; readonly labelKey: string }[];
    color: { value: string; onPick: (key: string) => void; onPreview?: (hex: string | null) => void } | null;
    close: () => void;
    glyph: (icon: string | undefined) => string;
    run: (id: string) => void;
}

export function projectMenuEntries(input: ProjectMenuInput): ItemMenuEntry[] {
    const { project, run } = input;
    const hidden = Boolean(project.archived_at);
    const go = (id: string) => () => run(id);
    const leaf = (label: string, icon: string, id: string, extra: Partial<ItemMenuEntry> = {}): ItemMenuEntry => ({ label, icon, id, onPick: go(id), ...extra });

    const open: ItemMenuEntry[] = hidden ? [] : [
        leaf(t('opscenter.tabs.new_agent'), 'agent', 'new-agent', { onPick: go('new-session') }),
        leaf(t('layout.row.load_blueprint'), 'load-blueprint', 'load-blueprint'),
    ];

    const identity: ItemMenuEntry[] = [leaf(t('sidebar.heading.rename'), 'rename', 'rename-project')];
    const color = project.name === '' ? null : input.color;
    if (color) {
        identity.push({
            label: t('projects.page.action.color'), icon: 'colour', id: 'pick-color', onPick: () => undefined,
            children: () => entryNodes([{ label: '', id: 'project-color', onPick: () => undefined, colors: { value: color.value, allowNone: true, onPick: color.onPick, onPreview: color.onPreview } }], input.glyph, input.close),
        });
    }
    if (project.name !== '') identity.push({ label: t('sidebar.company.branch'), icon: 'company', id: 'add-to-company', onPick: () => undefined, children: () => companyNodes(input) });
    if (project.root !== null) identity.push(leaf(t('sidebar.show_path.label'), 'show-path', 'show-path'));

    const lifecycle: ItemMenuEntry[] = hidden ? [] : [leaf(t('sidebar.heading.sleep'), 'sleep', 'sleep')];
    if (input.agentOffered && !hidden) lifecycle.push(leaf(t('projects.page.action.turn_on_agent'), 'agent', 'turn-on-agent'));
    if (typeof project.id === 'number' && !hidden) {
        lifecycle.push(leaf(t('projects.page.action.new_sessions_join_swarm'), 'swarm', 'swarm-new-sessions', { checked: project.new_sessions_join_swarm === true }));
    }
    if (project.pack_state === 'moved_away') lifecycle.push(leaf(t('projects.page.action.move_back'), 'send-to', 'migrate-back'));
    else if (!hidden) lifecycle.push(leaf(t('projects.page.action.move_computer'), 'send-to', 'migrate-project'));

    const tools: ItemMenuEntry[] = typeof project.id === 'number' ? [
        leaf(t('sessions.page.action.project_settings'), 'project-settings', PROJECT_SETTINGS),
        ...input.panels.map((panel) => leaf(t(panel.labelKey), 'project-settings', `${PROJECT_PANEL}${panel.id}`, { keyless: true })),
    ] : [];

    const state = project.storage?.state ?? 'unpacked';
    const packed = state === 'packed';
    const busy = !packed && state !== 'unpacked';
    const last: ItemMenuEntry[] = [];
    if (hidden && !busy && !packed) last.push(leaf(t('projects.page.action.pack_folder'), 'archive', 'pack-folder'));
    if (packed && !project.storage?.packed_in) last.push(leaf(t('projects.page.action.unpack_folder'), 'archive', 'unpack-folder'));
    if (hidden && !packed && !busy) last.push(leaf(t('projects.page.action.unarchive_project'), 'archive', 'unarchive-project'));
    if (!hidden) last.push(leaf(t('projects.page.action.archive_project'), 'archive', 'archive-project'));
    last.push(leaf(t('projects.page.action.delete_project'), 'close', 'delete-project', { danger: true }));

    return spaced([open, identity, lifecycle, tools, last]);
}

function companyNodes(input: ProjectMenuInput): MenuNode[] {
    const { project, run } = input;
    const byName = [...input.companies].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }));
    const entries: ItemMenuEntry[] = byName.map((c) => ({
        label: c.name, id: `${SET_COMPANY}${c.id}`, danger: c.id === project.company_id, onPick: () => run(`${SET_COMPANY}${c.id}`),
    }));
    entries.push({ label: t('projects.page.action.new_company'), icon: 'new-in-folder', id: 'new-company', separatorBefore: byName.length > 0, onPick: () => run('new-company-for-project') });
    if (typeof project.company_id === 'number') entries.push({ label: t('projects.page.action.remove_from_company'), icon: 'remove-from-group', id: 'remove-from-company', onPick: () => run('remove-from-company') });
    return entryNodes(entries, input.glyph, input.close);
}
