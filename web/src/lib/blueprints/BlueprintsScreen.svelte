
<script lang="ts">
    import { captureOpener, restoreOpenerFocus } from '../dialog-frame/opener-focus';
    import ManagerFrame from '../manager-frame/ManagerFrame.svelte';
    import { createManagerController } from '../manager-frame/manager-controller.svelte';
    import { MANAGER_KEYS } from '../manager-frame/manager-model';
    import type { ManagerAdapter, ManagerItem } from '../manager-frame/types';
    import { t as appT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import { providerMark } from '../sessions/agent-marks';
    import { openModal } from '../modal';
    import { Button, List, ListRow } from '../base';
    import BlueprintEditorModal from './BlueprintEditorModal.svelte';
    import LaunchModal from './LaunchModal.svelte';
    import ExportModal from './ExportModal.svelte';
    import ImportModal from './ImportModal.svelte';
    import { blueprintError, deleteBlueprint } from './api';
    import { createBlueprintsAdapter, type BlueprintItem } from './blueprints-adapter';
    import type { Blueprint, SessionSpec } from './types';

    interface Props {
        adapter?: ManagerAdapter;
        t?: Translate;
        embedded?: boolean;
    }

    const { adapter, t = appT, embedded = false }: Props = $props();

    // svelte-ignore state_referenced_locally
    const ctl = createManagerController(adapter ?? createBlueprintsAdapter(t), t(MANAGER_KEYS.errorTitle));

    // svelte-ignore state_referenced_locally
    let open = $state(embedded);
    let opener: HTMLElement | null = null;
    let query = $state('');
    let selectedId = $state<string | null>(null);
    let removing = $state<string | null>(null);
    let sortKey = $state<'name' | 'recent'>('name');
    const sorted = $derived(
        [...ctl.items].sort((a, b) =>
            sortKey === 'recent'
                ? (b as BlueprintItem).blueprint.updated_at.localeCompare((a as BlueprintItem).blueprint.updated_at)
                : a.name.localeCompare(b.name),
        ),
    );
    let notice = $state<{ id: string; text: string; error: boolean } | null>(null);

    // svelte-ignore state_referenced_locally
    if (embedded) void ctl.load();

    export function show(): void {
        if (open) return;
        opener = captureOpener();
        open = true;
        void ctl.load();
    }

    export function close(): void {
        if (!open || embedded) return;
        open = false;
        selectedId = null;
        notice = null;
        restoreOpenerFocus(opener);
        opener = null;
    }

    export function isOpen(): boolean {
        return open;
    }

    function blueprintOf(item: ManagerItem): Blueprint {
        return (item as BlueprintItem).blueprint;
    }

    function folderLine(session: SessionSpec): string {
        return session.folder.mode === 'worktree'
            ? t('blueprint.launch.worktree', { path: session.folder.repo_path, branch: session.folder.branch })
            : t('blueprint.launch.existing', { path: session.folder.path });
    }

    async function openEditor(uuid: string | null, initial: Blueprint['spec'] | null): Promise<void> {
        const box: { saved: Blueprint | null } = { saved: null };
        const confirmed = await openModal(BlueprintEditorModal, {
            uuid,
            initial,
            onSaved: (blueprint: Blueprint) => {
                box.saved = blueprint;
            },
        });
        if (confirmed && box.saved) {
            selectedId = box.saved.blueprint_uuid;
            notice = { id: box.saved.blueprint_uuid, text: t('blueprint.saved', { name: box.saved.name }), error: false };
            await ctl.load();
        }
    }

    function openNew(): Promise<void> {
        return openEditor(null, null);
    }

    function openEdit(blueprint: Blueprint): Promise<void> {
        return openEditor(blueprint.blueprint_uuid, blueprint.spec);
    }

    async function openLaunch(blueprint: Blueprint): Promise<void> {
        await openModal(LaunchModal, { uuid: blueprint.blueprint_uuid, name: blueprint.name });
    }

    async function openExportOne(blueprint: Blueprint): Promise<void> {
        await openModal(ExportModal, { uuid: blueprint.blueprint_uuid });
    }

    async function openImport(): Promise<void> {
        const box: { imported: Blueprint | null } = { imported: null };
        const confirmed = await openModal(ImportModal, {
            onImported: (blueprint: Blueprint) => {
                box.imported = blueprint;
            },
        });
        if (confirmed && box.imported) {
            selectedId = box.imported.blueprint_uuid;
            notice = { id: box.imported.blueprint_uuid, text: t('blueprint.import.done', { name: box.imported.name }), error: false };
            await ctl.load();
        }
    }

    function confirmRemoval(name: string): Promise<boolean> {
        const app = (globalThis as { App?: { showConfirmModal?: (...args: string[]) => Promise<boolean> } }).App;
        if (!app?.showConfirmModal) return Promise.resolve(false);
        return app.showConfirmModal(
            t('blueprint.remove'),
            t('blueprint.remove.message', { name }),
            '',
            t('blueprint.remove'),
            t('blueprint.cancel'),
            'danger',
        );
    }

    async function removeOne(blueprint: Blueprint): Promise<void> {
        if (!(await confirmRemoval(blueprint.name))) return;
        removing = blueprint.blueprint_uuid;
        try {
            await deleteBlueprint(blueprint.blueprint_uuid);
            selectedId = null;
            notice = null;
            await ctl.load();
        } catch (err) {
            notice = { id: blueprint.blueprint_uuid, text: t('blueprint.save_failed', { reason: blueprintError(err).detail }), error: true };
        }
        removing = null;
    }
</script>

{#if open}
    <ManagerFrame
        title={t('blueprint.title')}
        items={sorted}
        kit
        viewKey="blueprints"
        defaultView="grid"
        sort={{
            label: t(MANAGER_KEYS.sortLabel),
            value: sortKey,
            options: [
                { value: 'name', label: t('blueprint.sort.name') },
                { value: 'recent', label: t('blueprint.sort.recent') },
            ],
        }}
        onSort={(next) => (sortKey = next === 'recent' ? 'recent' : 'name')}
        status={ctl.status}
        {query}
        onQuery={(next) => (query = next)}
        {selectedId}
        onSelect={(id) => {
            selectedId = id;
            notice = null;
        }}
        onRetry={() => void ctl.load()}
        onClose={embedded ? undefined : close}
        emptyText={t('blueprint.empty')}
        {embedded}
        {t}
    >
        {#snippet actions()}
            <Button data-blueprint-import-open onclick={() => void openImport()}>{t('blueprint.import')}</Button>
            <Button variant="confirm" data-blueprint-new-open onclick={() => void openNew()}>{t('blueprint.new')}</Button>
        {/snippet}
        {#snippet cardExtra(item)}
            {@const blueprint = blueprintOf(item)}
            <List density="dense" label={t('blueprint.session.heading')}>
                {#each blueprint.spec.sessions as session (session.label)}
                    {@const mark = providerMark(session.family)}
                    <ListRow primary={session.label} secondary={folderLine(session)}>
                        {#snippet lead()}
                            <span class="bp-card__mark" data-agent-family={mark.key} role="img" aria-label={mark.label} title={mark.label}
                                >{@html mark.svg}</span
                            >
                        {/snippet}
                    </ListRow>
                {/each}
            </List>
            <div class="bp-card__actions">
                <Button variant="confirm" data-blueprint-launch onclick={() => void openLaunch(blueprint)}>{t('blueprint.launch')}</Button>
            </div>
        {/snippet}
        {#snippet detail(item)}
            {@const blueprint = blueprintOf(item)}
            <dl class="mgr-facts">
                <dt>{t('blueprint.name.label')}</dt>
                <dd>{blueprint.name}</dd>
                <dt>{t('blueprint.session.heading')}</dt>
                <dd data-blueprint-detail-count>{t('session.summary.sessions', { count: blueprint.spec.sessions.length })}</dd>
            </dl>
            <p class="bp-detail__heading">{t('blueprint.session.heading')}</p>
            <List label={t('blueprint.session.heading')}>
                {#each blueprint.spec.sessions as session (session.label)}
                    {@const mark = providerMark(session.family)}
                    <ListRow wrap primary={session.label} secondary={folderLine(session)}>
                        {#snippet lead()}
                            <span class="bp-card__mark" data-agent-family={mark.key} role="img" aria-label={mark.label} title={mark.label}
                                >{@html mark.svg}</span
                            >
                        {/snippet}
                    </ListRow>
                {/each}
            </List>
            <div class="bp-detail__actions">
                <Button data-blueprint-edit onclick={() => void openEdit(blueprint)}>{t('blueprint.edit')}</Button>
                <Button data-blueprint-export onclick={() => void openExportOne(blueprint)}>{t('blueprint.export')}</Button>
                <Button
                    variant="danger"
                    data-blueprint-remove
                    disabled={removing === blueprint.blueprint_uuid}
                    onclick={() => void removeOne(blueprint)}
                >
                    {t('blueprint.remove')}
                </Button>
            </div>
            {#if notice && notice.id === blueprint.blueprint_uuid}
                <p class={notice.error ? 'bp-detail__error' : 'bp-detail__notice'} role={notice.error ? 'alert' : 'status'}>{notice.text}</p>
            {/if}
        {/snippet}
    </ManagerFrame>
{/if}

<style>
    .bp-card__mark {
        display: inline-flex;
        flex: none;
        align-items: center;
        justify-content: center;
        width: 14px;
        height: 14px;
        line-height: 0;
        color: var(--oc-text-secondary);
    }

    .bp-card__actions {
        display: flex;
        margin-top: 10px;
    }

    .bp-detail__heading {
        margin: 16px 0 6px;
        color: var(--oc-text-secondary);
        font-size: 10px;
        letter-spacing: var(--oc-tracking-label, 0.6px);
        text-transform: uppercase;
    }

    .bp-detail__actions {
        display: flex;
        gap: 8px;
        margin-top: 16px;
    }

    .bp-detail__notice,
    .bp-detail__error {
        margin: 12px 0 0;
        padding: 6px 8px;
        border-left: 2px solid var(--oc-cyan);
        background: var(--oc-ground-field);
        color: var(--oc-text-primary);
        font-size: 12px;
        overflow-wrap: anywhere;
    }

    .bp-detail__error {
        border-left-color: var(--oc-coral);
    }
</style>
