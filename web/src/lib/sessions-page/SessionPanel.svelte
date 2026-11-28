
<script lang="ts">
    import { failureReason } from '../errors/failure-reason';
    import { untrack } from 'svelte';
    import { subscribe } from '../../opscenter/api/events.svelte';
    import { BookmarkWidgetActions } from '../../opscenter/cells/bookmarks/widget-actions.svelte';
    import { ageFormatter } from '../projects-shared/format';
    import { isKeptAwake } from '../auto-sleep/auto-sleep-store.svelte';
    import { togglePinRow } from '../sidebar-shell/row-reorder';
    import type { Translate } from '../sessions/types';
    import type { PageRow } from './filters';
    import PanelBelongs from './PanelBelongs.svelte';
    import PanelBookmarks from './PanelBookmarks.svelte';
    import PanelConversations from './PanelConversations.svelte';
    import PanelFacts from './PanelFacts.svelte';
    import PanelHead from './PanelHead.svelte';
    import PanelNow from './PanelNow.svelte';
    import { PanelData, defaultPanelReaders, type PanelReaders } from './panel-data.svelte';
    import { pinnedUuidSet } from './pins';
    import type { PanelAction } from './row-action';
    import type { SessionsData } from './sessions-data.svelte';
    import './sessions-panel.css';

    interface Props {
        row: PageRow | null;
        ready: boolean;
        data: SessionsData;
        t: Translate;
        now: () => number;
        onClose: () => void;
        onAct: (kind: PanelAction, row: PageRow) => void;
        readers?: PanelReaders;
        busyIds?: ReadonlySet<string>;
    }
    const { row, ready, data, t, now, onClose, onAct, readers = defaultPanelReaders, busyIds = new Set<string>() }: Props = $props();

    // svelte-ignore state_referenced_locally
    const panel = new PanelData(readers);
    const marksActions = new BookmarkWidgetActions();
    let resumeNotice = $state<{ text: string; error: boolean } | null>(null);
    let groupTick = $state(0);

    const uuid = $derived(row?.s.session_uuid ?? null);
    const live = $derived(row ? data.live(row.s) : undefined);
    const claude = $derived(row?.provider === 'claude');
    const running = $derived(row?.s.state === 'running');
    const remote = $derived(row ? row.computer !== null : false);
    const gone = $derived(row ? row.s.has_transcript === false && !row.s.offloaded : false);
    const pinned = $derived.by(() => {
        void data.pinTick;
        return uuid !== null && pinnedUuidSet().has(uuid);
    });
    const keptAwake = $derived(row && !remote ? isKeptAwake(row.s.tmux_name) === true : false);
    const age = $derived(ageFormatter(t, now));

    $effect(() => {
        const id = uuid;
        if (!id || remote) {
            untrack(() => panel.stop());
            return;
        }
        untrack(() => {
            resumeNotice = null;
            marksActions.notice = null;
            marksActions.armed = false;
            panel.follow(id, claude, row?.s.row_id ?? null);
        });
        return () => panel.stop();
    });

    $effect(() => {
        let timer: ReturnType<typeof setTimeout> | undefined;
        const off = subscribe('sessions.changed', () => {
            clearTimeout(timer);
            timer = setTimeout(() => (groupTick += 1), 250);
        });
        return () => {
            clearTimeout(timer);
            off();
        };
    });

    function pin(r: PageRow): void {
        if (!r.s.tmux_name || r.computer !== null) return;
        togglePinRow(r.s.tmux_name);
        data.pinTick += 1;
    }

    async function resume(conversationId: string): Promise<void> {
        resumeNotice = null;
        try {
            if (await panel.resume(conversationId)) resumeNotice = { text: t('sessions.page.panel.conv.resumed'), error: false };
        } catch (error) {
            resumeNotice = { text: failureReason(error), error: true };
        }
    }

    function onKey(e: KeyboardEvent): void {
        if (e.key !== 'Escape' || e.defaultPrevented) return;
        const target = e.target instanceof HTMLElement ? e.target : null;
        if (target && (/^(INPUT|SELECT|TEXTAREA)$/.test(target.tagName) || target.isContentEditable)) return;
        onClose();
    }
</script>

<svelte:window onkeydown={onKey} />

<div class="sp-pn" id="sp-pn" data-open role="group" aria-label={t('sessions.page.panel.label')}>
    <div class="sp-pn-scroll">
        {#if row}
            {#key row.s.session_uuid}
                <div class="sp-pn-body">
                    <PanelHead {row} {live} asleepUnread={data.asleepUnread(row.s.session_uuid)} {pinned} {keptAwake} {t} {onAct} onPin={pin} busy={busyIds.has(row.s.session_uuid)} />
                    <PanelBelongs sessionUuid={row.s.session_uuid} {t} tick={groupTick} />
                    <PanelNow {row} {live} listingDown={data.listingDown} {t} now={now()} />
                    {#if !remote}
                        <PanelConversations list={panel.conversations} timeline={panel.timeline} codex={row.provider === 'codex'} {gone} status={panel.convStatus} resuming={panel.resuming} notice={resumeNotice} {t} onResume={(id) => void resume(id)} />
                        <PanelBookmarks list={panel.bookmarks} status={panel.marksStatus} running={Boolean(running)} {gone} {claude} rowId={row.s.row_id ?? 0} actions={marksActions} {t} now={now()} />
                    {/if}
                    <PanelFacts {row} worked={data.usage ? (data.usage[row.s.session_uuid] ?? null) : null} previous={data.conversations[row.s.session_uuid] ?? 0} {t} {age} />
                </div>
            {/key}
        {:else if ready}
            <p class="sp-pn-note sp-pn-sec" data-missing>{t('projects.page.session_not_found')}</p>
        {:else}
            <p class="sp-pn-note sp-pn-sec">{t('sessions.page.loading')}</p>
        {/if}
    </div>
</div>
