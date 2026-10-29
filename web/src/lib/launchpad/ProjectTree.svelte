<!-- could not -->
<script lang="ts">
    import AttentionGroup from './AttentionGroup.svelte';
    import NoProjectGroup from './NoProjectGroup.svelte';
    import ProjectNode from './ProjectNode.svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import {
        archivedNoticeText,
        authorityBannerText,
        PROJECT_TREE_KEYS,
    } from '../../../../client/js/labels/project-tree.js';
    import { sessionStore } from '../sessions/store.svelte';
    import { archivedNotice, authorityBanner } from './project-chrome';
    import { buildProjectSessionGroups } from './project-groups';
    import { projectNodeView } from './project-node';
    import {
        browserControl,
        type ProjectChromeControl,
    } from './project-chrome-control';
    import {
        browserProjectTreeHost,
        type ProjectTreeHost,
    } from './project-tree-host';
    import { uiPrefs } from '../ui/prefs.svelte';
    import type { Translate } from '../sessions/types';

    interface Props {
        host?: ProjectTreeHost;
        control?: ProjectChromeControl;
        transports?: Map<string, string>;
        t?: Translate;
    }

    let {
        host = browserProjectTreeHost(),
        control = browserControl(),
        transports = new Map<string, string>(),
        t = reactiveT,
    }: Props = $props();

    async function toggleArchivedProjects(): Promise<void> {
        uiPrefs.setArchivedProjectsVisible(!uiPrefs.archivedProjectsVisible);
        await host.reloadProjects();
    }

    $effect(() => {
        const on = uiPrefs.archivedProjectsVisible;
        control.setArchivedToggle(
            on,
            on
                ? t(PROJECT_TREE_KEYS.archivedHide)
                : t(PROJECT_TREE_KEYS.archivedShow),
        );
    });

    $effect(() => {
        control.bindArchivedToggle(() => void toggleArchivedProjects());
    });

    const groups = $derived(
        buildProjectSessionGroups({
            runningSessions: sessionStore.runningSessions,
            sessionRecords: sessionStore.sessionRecords,
            sessionAttribution: sessionStore.sessionAttribution,
            sessionAttributionByInstance: sessionStore.sessionAttributionByInstance,
            sessionAttributionAmbiguous: sessionStore.sessionAttributionAmbiguous,
            sessionAttributionListingOk: sessionStore.sessionAttributionListingOk,
            sessionAttributionListingDetail: sessionStore.sessionAttributionListingDetail,
        }),
    );

    const nodes = $derived(
        sessionStore.projects.map((project, index) =>
            projectNodeView(project, index, {
                presence: sessionStore.projectPresence,
                byProjectId: groups.byProjectId,
            }),
        ),
    );

    const banner = $derived(authorityBannerText(
        authorityBanner(sessionStore.projectAuthority), t,
    ));
    const archived = $derived(archivedNoticeText(
        archivedNotice(sessionStore.archivedFetchOk, sessionStore.projects), t,
    ));
    const authorityState = $derived(authorityBanner(sessionStore.projectAuthority));
    const archivedState = $derived(
        archivedNotice(sessionStore.archivedFetchOk, sessionStore.projects),
    );
</script>

{#if banner}
    <div
        class="project-authority-banner"
        role={authorityState.kind === 'degraded' ? 'alert' : 'status'}
        class:project-authority-banner-unknown={authorityState.kind === 'unknown'}
        class:project-authority-banner-unreadable={authorityState.kind === 'degraded'}
        data-authority-state={authorityState.kind === 'degraded'
            ? authorityState.mode
            : 'unknown'}
        data-writable={authorityState.kind === 'degraded'
            ? String(authorityState.writable)
            : undefined}
    >
        {banner}
    </div>
{/if}

{#if archived}
    <div
        class="project-archived-notice"
        role="status"
        class:project-archived-notice--unknown={archivedState.kind === 'unknown'}
    >
        {archived}
    </div>
{/if}

{#if nodes.length === 0}
    <div class="launchpad-empty">
        {t(PROJECT_TREE_KEYS.emptyTitle)}<br />
        <small>{t(PROJECT_TREE_KEYS.emptyHint)}</small>
    </div>
{:else}
    
    {#each nodes as view (view.nodeKey)}
        <ProjectNode
            {view}
            workStamps={sessionStore.workStampByName}
            {transports}
            {host}
            {t}
        />
    {/each}
{/if}

<NoProjectGroup
    sessions={groups.noProject}
    workStamps={sessionStore.workStampByName}
    {transports}
    {host}
    {t}
/>
<AttentionGroup items={groups.needsAttention} {host} {t} />
