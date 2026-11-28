<!-- a dialog is open -->
<script lang="ts">
    import { auth } from '../../opscenter/api/auth.svelte';
    import IconButton from '../base/IconButton.svelte';
    import '../projects-shared/projects-shared.css';
    import AnchoredPopup from '../dialog-frame/AnchoredPopup.svelte';
    import SlotHost from '../cplug-ui/SlotHost.svelte';
    import ViewFrame from '../cplug-ui/ViewFrame.svelte';
    import { pluginDisplayName, resolveProjectPanelEntries, runSlotDescriptorAction } from '../plugins/slot-actions';
    import { pluginsStore } from '../plugins/store.svelte';
    import type { Translate } from '../sessions/types';
    import ProjectTransport, { type DeckPage } from '../pack-transport/ProjectTransport.svelte';
    import { ageFormatter } from '../projects-shared/format';
    import { previewOf } from '../projects-shared/ledger-model';
    import { projectPanels, type PanelReadState } from '../../plugins/sdk/project-panels';
    import { openModalCount } from '../modal';
    import type { ProjectTool } from './project-tools';

    interface Props {
        tool: ProjectTool;
        project: { id: number; name: string };
        t: Translate;
        onClose: () => void;
    }
    const { tool, project, t, onClose }: Props = $props();

    let page = $state<DeckPage>('home');

    $effect(() => {
        if (tool.kind !== 'slot-panel' || auth.state === 'signed-out') return;
        return pluginsStore.acquire({ includeSlots: true });
    });

    const panel = $derived(tool.kind === 'panel' ? (projectPanels().find((p) => p.id === tool.panelId) ?? null) : null);
    const Panel = $derived(panel?.component);
    const slotPanel = $derived.by(() => {
        if (tool.kind !== 'slot-panel') return null;
        void pluginsStore.rows;
        void pluginsStore.slots;
        return resolveProjectPanelEntries().find((p) => p.pluginId === tool.pluginId && p.entryId === tool.entryId) ?? null;
    });
    const slotRow = $derived(tool.kind === 'slot-panel' ? pluginsStore.rowOf(tool.pluginId) : undefined);
    const age = $derived(ageFormatter(t, () => Date.now()));
    const title = $derived(
        tool.kind === 'settings'
            ? t('sessions.page.tool.settings_title', { name: project.name })
            : tool.kind === 'panel'
              ? t('sessions.page.tool.panel_title', { panel: panel ? t(panel.labelKey) : '', name: project.name })
              : t('sessions.page.tool.panel_title', { panel: slotPanel?.label ?? tool.entryId, name: project.name }),
    );
    const dataProjectTool = $derived(
        tool.kind === 'panel'
            ? tool.panelId
            : tool.kind === 'slot-panel'
              ? `${tool.pluginId}:${tool.entryId}`
              : 'settings',
    );

    function tally(count: number, read: PanelReadState): string {
        if (read === 'loading') return t('projects.page.group.reading');
        if (read === 'failed') return t('projects.page.group.unread');
        return count ? String(count) : t('projects.page.group.none');
    }
</script>


<AnchoredPopup class="pw" tabindex={-1} label={title} data-project-tool={dataProjectTool}
    placement="manual" initialFocus="self" dismissable={() => openModalCount() === 0} {onClose}>
    <div class="pw-title">
        {#if tool.kind === 'settings' && page !== 'home'}
            <IconButton icon="chevron-right" iconSize={14} variant="quiet" label={t('pack.deck.back')} data-back onclick={() => (page = 'home')} />
        {/if}
        <span class="pw-label">{title}{#if tool.kind === 'settings' && page !== 'home'}<span class="dk-crumb" data-crumb><i>/</i>{t(`pack.deck.page.${page}`)}</span>{/if}</span>
        <IconButton icon="close" variant="danger" label={t('sessions.page.tool.close')} data-project-tool-close onclick={onClose} />
    </div>
    <div class="pw-body ph-page" class:pw-body--deck={tool.kind === 'settings'}>
        {#if tool.kind === 'settings'}
            
            <ProjectTransport name={`id:${project.id}`} bind:page />
        {:else if Panel}
            {#snippet header(count: number, read: PanelReadState)}
                <div class="pw-tally" data-project-tool-tally>{tally(count, read)}</div>
            {/snippet}
            <div class="ph-table">
                <Panel projectId={project.id} projectKey={String(project.id)} {header} isFolded={() => false} {age} {previewOf} />
            </div>
        {:else if tool.kind === 'slot-panel'}
            {#if slotPanel?.view}
                <ViewFrame
                    plugin={{
                        cplugId: tool.pluginId,
                        name: pluginDisplayName(tool.pluginId, slotRow),
                        unverified: slotRow?.unverified === true,
                        declared: { routes: slotRow?.routes ?? [], tools: slotRow?.declared_tools ?? [] },
                        installKey: slotRow?.install_key ?? tool.pluginId,
                    }}
                    view={slotPanel.view}
                    surface="panel"
                    bar={false}
                    {t}
                />
            {:else if slotPanel}
                <SlotHost
                    slot="project.panels"
                    items={[slotPanel.contribution]}
                    layout="column"
                    run={(_entry, action) =>
                        runSlotDescriptorAction(
                            tool.pluginId,
                            action.kind === 'route' || action.kind === 'tool' || action.kind === 'macro'
                                ? {
                                      ...action,
                                      payload: {
                                          project_id: project.id,
                                          project_key: String(project.id),
                                          ...(action.payload ?? {}),
                                      },
                                  }
                                : action,
                        )}
                    {t}
                />
            {:else}
                <p class="pw-tally" data-project-tool-empty>{t('cplug_ui.nothing_here')}</p>
            {/if}
        {/if}
    </div>
</AnchoredPopup>

<style>
    @layer components {
        :global(.pw[data-project-tool]) {
            position: fixed;
            z-index: var(--oc-z-palette);
            inset: 12vh auto auto 50%;
            transform: translateX(-50%);
            margin: 0;
            width: min(760px, calc(100vw - 16px));
            max-height: 76vh;
            display: flex;
            flex-direction: column;
            box-sizing: border-box;
            color: var(--oc-text-primary);
            overflow: hidden;
        }

        .pw-title {
            flex: none;
            display: flex;
            align-items: center;
            gap: var(--oc-space-2);
            min-height: 30px;
            padding: 0 var(--oc-space-3);
            background: var(--oc-ground-titlerow);
            box-shadow: inset 0 -1px 0 var(--oc-line-faint);
        }

        .pw-label {
            flex: 1 1 auto;
            min-width: 0;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            font-family: var(--font-mono);
            font-size: var(--oc-fs-label, 11px);
            letter-spacing: var(--oc-tracking-label, 0.6px);
            text-transform: uppercase;
            color: var(--oc-orange);
        }

        .pw-body {
            flex: 1 1 auto;
            min-height: 0;
            overflow: auto;
            padding: var(--oc-space-2) 0;
        }

        .pw-body--deck {
            display: flex;
            flex-direction: column;
            padding: 0;
            overflow: hidden;
        }

        .pw-body--deck > :global(.dk-body) {
            flex: 1 1 auto;
        }

        :global(.pw-title [data-back]) {
            flex: none;
            margin-left: -8px;
            transform: rotate(180deg);
        }

        .pw-tally {
            padding: 0 var(--oc-space-3);
            font-size: var(--oc-fs-micro, 10px);
            letter-spacing: var(--oc-tracking-label, 0.6px);
            text-transform: uppercase;
            color: var(--oc-text-dim);
        }
    }
</style>
