
<script lang="ts">
    import Button from '../base/Button.svelte';
    import SessionFace from '../sessions/SessionFace.svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import { sessionStore } from '../sessions/store.svelte';
    import { uiPrefs } from '../ui/prefs.svelte';
    import { RECENT_KEYS } from '../../../../client/js/labels/recent-session.js';
    import { recentView, type RestartOptions, type Translate } from './recent';
    import {
        archiveSessionRecord,
        browserHost,
        restartRecentSession,
        type RecentHost,
    } from './recent-actions';
    import { browserChrome, type RecentChrome } from './recent-chrome';
    import { openStatusKey, recentOpenStatus } from './recent-open-status.svelte';

    interface Props {
        host?: RecentHost;
        chrome?: RecentChrome;
        t?: Translate;
    }

    let {
        host = browserHost(() => refresh()),
        chrome = browserChrome(),
        t = reactiveT,
    }: Props = $props();

    // svelte-ignore state_referenced_locally
    let live = $state(host.liveSessions());

    const view = $derived(
        recentView(
            sessionStore.recentPayload,
            live,
            uiPrefs.archivedSessionsVisible,
            (name) => host.deriveDisplayName(name),
            t,
        ),
    );

    let restarting = $state<Record<string, boolean>>({});

    async function onRestart(opts: RestartOptions): Promise<void> {
        const key = opts.sessionUuid || opts.title;
        if (restarting[key]) return;
        restarting[key] = true;
        try {
            await restartRecentSession(opts, host, t);
        } finally {
            delete restarting[key];
        }
    }

    export async function refresh(): Promise<void> {
        await sessionStore.refreshRecent(
            (includeArchived) => host.fetchRecent(includeArchived),
            uiPrefs.archivedSessionsVisible,
            t,
        );
        live = host.liveSessions();
    }

    async function toggleArchived(): Promise<void> {
        uiPrefs.setArchivedSessionsVisible(!uiPrefs.archivedSessionsVisible);
        await refresh();
    }

    $effect(() => {
        chrome.setCount(
            view.kind === 'hidden' ? '' : view.count,
            view.kind === 'unavailable' ? view.state : 'ok',
        );
        chrome.setSectionVisible(view.kind !== 'hidden');
    });

    $effect(() => {
        const on = uiPrefs.archivedSessionsVisible;
        chrome.setArchiveToggle(on, t(on ? RECENT_KEYS.archiveHide : RECENT_KEYS.archiveShow));
    });

    // svelte-ignore state_referenced_locally
    chrome.bindArchiveToggle(() => {
        void toggleArchived();
    });

    void refresh();
</script>

{#if view.kind === 'unavailable'}
    <div class="recent-sessions-attention" role="status" data-state={view.state}>
        <div class="recent-sessions-attention__title">{view.title}</div>
        <div class="recent-sessions-attention__detail">{view.detail}</div>
    </div>
{:else if view.kind === 'empty'}
    <div class="launchpad-empty">{view.message}</div>
{:else if view.kind === 'rows'}
    {#each view.rows as row (row.uuid || row.name)}
        <div
            class="recent-session-row"
            class:recent-session-row--deleted={row.archived}
            data-uuid={row.uuid}
            data-lifecycle={row.lifecycle}
            data-deleted={row.archived ? '1' : undefined}
        >
            <!-- could not -->
            {#if row.canRestart}
                <SessionFace row={{}} lifecycle="stopped" />
            {/if}
            <span class="recent-session-name">{row.name}</span>
            <span class="recent-session-lifecycle">{row.lifecycleLabel}</span>
            
            {#if row.archived}
                <span
                    class="recent-session-deleted"
                >{t(RECENT_KEYS.archiveBadge)}</span>
            {/if}
            {#if row.restart}
                {@const open = recentOpenStatus.of(openStatusKey(row.restart.sessionUuid, row.restart.title))}
                
                {#if open?.phase === 'failed'}
                    <span class="recent-session-open-error" role="alert">{t(RECENT_KEYS.restartRowFailed, { reason: open.reason })}</span>
                {/if}
                <Button
                    variant="confirm"
                    size="sm"
                    data-record-action="restart"
                    data-uuid={row.restart.sessionUuid}
                    data-title={row.restart.title}
                    data-working-dir={row.restart.workingDir}
                    data-agent-type={row.restart.agentType}
                    disabled={!!restarting[row.restart.sessionUuid || row.restart.title]}
                    aria-busy={!!restarting[row.restart.sessionUuid || row.restart.title]}
                    onclick={() => row.restart && onRestart(row.restart)}
                >{open?.phase === 'opening' ? t(RECENT_KEYS.restartPending) : t(RECENT_KEYS.restartAction)}</Button>
            {/if}
            
            {#if !row.archived}
                <Button
                    size="sm"
                    data-record-action="archive"
                    data-uuid={row.uuid}
                    aria-label={t(RECENT_KEYS.archiveActionAria)}
                    onclick={() => archiveSessionRecord(row.uuid, host, t)}
                >{t(RECENT_KEYS.archiveAction)}</Button>
            {/if}
        </div>
    {/each}
{/if}

<style>
  @layer components {
    .recent-session-open-error {
        color: var(--oc-coral);
        font-size: 0.75rem;
        overflow-wrap: anywhere;
    }
  }
</style>
