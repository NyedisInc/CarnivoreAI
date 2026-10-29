
<script lang="ts">
    import Glyph from '../Glyph.svelte';
    import IconButton from '../base/IconButton.svelte';
    import { buttonAttrs } from '../base/classes';
    import TreeSessionRows from './TreeSessionRows.svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import {
        PROJECT_TREE_KEYS,
        presenceBadgeText,
        sessionCountLabel,
        workTitle,
    } from '../../../../client/js/labels/project-tree.js';
    import { treeCollapse } from './tree-collapse.svelte';
    import type { ProjectNodeView } from './project-node';
    import type { ProjectTreeHost } from './project-tree-host';
    import type { Translate } from '../sessions/types';

    interface Props {
        view: ProjectNodeView;
        workStamps: Map<string, string>;
        transports?: Map<string, string>;
        host: ProjectTreeHost;
        t?: Translate;
    }

    let {
        view,
        workStamps,
        transports = new Map<string, string>(),
        host,
        t = reactiveT,
    }: Props = $props();

    const collapsed = $derived(treeCollapse.isCollapsed(view.nodeKey));
    const sessionsId = $derived('project-node-sessions-' + view.nodeKey);
    const presenceText = $derived(
        presenceBadgeText(view.presenceState, view.presenceDetail, t),
    );

    let itemEl: HTMLDivElement | null = $state(null);

    function openOrRefuse(): void {
        if (view.isDisabled) {
            host.explainRefused(view.project, itemEl);
            return;
        }
        host.selectProject(view.project);
    }

    async function toggleArchived(): Promise<void> {
        if (view.isArchived) await host.unarchiveProject(view.name);
        else await host.archiveProject(view.name);
    }
</script>

<div
    class="project-node"
    class:project-node--archived={view.isArchived}
    data-project-node="project"
    data-project-name={view.name}
    data-work={view.work.state}
    data-work-at={view.work.at}
>
    <div class="project-node__row">
        
        <div class="project-node__gutter">
            {#if view.foldable}
                <button
                    type="button"
                    class="project-node__toggle"
                    data-node-key={view.nodeKey}
                    aria-expanded={!collapsed}
                    aria-label={t(PROJECT_TREE_KEYS.toggleAria, { name: view.name })}
                    aria-controls={view.hasChildren ? sessionsId : undefined}
                    onclick={() => treeCollapse.toggle(view.nodeKey)}
                >
                    <span class="project-node__chevron" aria-hidden="true">&#9658;</span>
                    
                    {#if view.hasChildren}
                        <span class="project-node__count">{view.children.length}</span>
                    {/if}
                </button>
            {/if}
        </div>
        <!-- anchor: svelte-ignore role="button" -->
        <!-- svelte-ignore a11y_click_events_have_key_events -->
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div
            bind:this={itemEl}
            class="project-item"
            class:project-presence-disabled={view.isDisabled}
            class:project-presence-missing={view.presenceState === 'missing'}
            class:project-presence-unreachable={view.presenceState === 'unreachable'}
            class:project-item--archived={view.isArchived}
            data-index={view.index}
            data-name={view.name}
            aria-disabled={view.isDisabled ? 'true' : undefined}
            onclick={openOrRefuse}
        >
            
            <IconButton
                label={t(PROJECT_TREE_KEYS.actionEdit)}
                variant="quiet"
                data-project-key="edit"
                data-name={view.name}
                disabled={view.isDisabled}
                onclick={(e) => {
                    e.stopPropagation();
                    host.editProject(view.project);
                }}><Glyph name="pencil" /></IconButton
            >
            
            <button
                type="button"
                {...buttonAttrs('quiet', 'icon')}
                title={view.isArchived
                    ? t(PROJECT_TREE_KEYS.actionRestoreTitle)
                    : t(PROJECT_TREE_KEYS.actionArchiveTitle)}
                aria-label={view.isArchived
                    ? t(PROJECT_TREE_KEYS.actionRestoreAria)
                    : t(PROJECT_TREE_KEYS.actionArchiveAria)}
                data-project-key="archive"
                data-name={view.name}
                data-archived={view.isArchived ? '1' : '0'}
                onclick={(e) => {
                    e.stopPropagation();
                    void toggleArchived();
                }}
                >{#if view.isArchived}&#x21ba;{:else}<Glyph name="archive" />{/if}</button
            >
            <div class="project-name">&raquo; {view.name}</div>
            <div class="project-path">{view.path}</div>
            
            {#if view.hasDescription}
                <div class="project-description" style:display={collapsed ? 'none' : null}>
                    {view.description}
                </div>
            {/if}
            {#if view.isArchived}
                <div class="project-archived-badge">{t(PROJECT_TREE_KEYS.badgeArchived)}</div>
            {/if}
            {#if presenceText}
                <div
                    class={[
                        'project-presence-badge',
                        `project-presence-badge-${view.presenceState}`,
                    ]}
                >
                    {presenceText}
                </div>
            {/if}
        </div>
    </div>
    {#if view.hasChildren}
        <div
            class="project-node__sessions"
            id={sessionsId}
            style:display={collapsed ? 'none' : null}
        >
            <TreeSessionRows
                sessions={view.children}
                {workStamps}
                {transports}
                {host}
                {t}
            />
        </div>
    {/if}
</div>
