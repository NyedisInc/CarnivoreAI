<!-- conversation id -->
<script lang="ts">
    import Button from '../base/Button.svelte';
    import List from '../base/List.svelte';
    import ListRow from '../base/ListRow.svelte';
    import type { Translate } from '../sessions/types';
    import type { SessionTimeline } from '../../opscenter/cells/timeline/types';
    import { conversationsOf, timelineOf, type PanelConversations } from './panel-data.svelte';
    import { dateWord } from './latest-line';

    interface Props {
        list: PanelConversations | null;
        timeline: SessionTimeline | null;
        codex: boolean;
        gone: boolean;
        status: 'idle' | 'loading' | 'ready' | 'error';
        resuming: string | null;
        notice: { text: string; error: boolean } | null;
        t: Translate;
        onResume: (conversationId: string) => void;
    }
    const { list, timeline, codex, gone, status, resuming, notice, t, onResume }: Props = $props();

    const convs = $derived(conversationsOf(list));

    function busyWord(seconds: number): string {
        const minutes = Math.round(seconds / 60);
        if (minutes < 1) return t('sessions.page.panel.conv.busy_under');
        const h = Math.floor(minutes / 60);
        return h ? `${h}h ${String(minutes % 60).padStart(2, '0')}m` : `${minutes}m`;
    }

    function endedWord(reason: string | null): string {
        if (!reason) return t('sessions.page.panel.ended.none');
        const key = `sessions.page.panel.ended.${reason}`;
        const word = t(key);
        return word === key ? reason : word;
    }
</script>

<section class="sp-pn-sec" id="sp-pn-convs">
    <h3 class="pl-label">{t('sessions.page.panel.convs')}</h3>
    {#if status === 'error'}
        <p class="sp-pn-note">{t('sessions.page.panel.history_failed')}</p>
    {:else if status !== 'ready'}
        <p class="sp-pn-note">{t('sessions.page.loading')}</p>
    {:else if convs.length === 0}
        <p class="sp-pn-note">{t('sessions.page.panel.conv.none')}</p>
    {:else}
        {#if gone}<p class="sp-pn-note">{t('sessions.page.panel.conv.marks_gone')}</p>
        {:else if codex}<p class="sp-pn-note">{t('sessions.page.panel.conv.marks_codex')}</p>{/if}
        <List class="sp-pn-list" label={t('sessions.page.panel.convs')}>
            {#snippet children()}
                {#each convs as c (c.conversation_id)}
                    {@const tl = timelineOf(timeline, c.conversation_id)}
                    <ListRow wrap data-conv={c.conversation_id}>
                        {#snippet children()}
                            <div class="sp-pn-lt">
                                <span>{dateWord(c.started_at)}{c.ended_at && dateWord(c.ended_at) !== dateWord(c.started_at) ? ` ${t('sessions.page.panel.conv.to')} ${dateWord(c.ended_at)}` : ''}</span>
                                <span class="sp-pn-dim">{c.current ? t('sessions.page.panel.conv.current') : t('sessions.page.panel.conv.ended_by', { reason: endedWord(c.ended_reason) })}</span>
                                {#if tl.busySeconds !== null}<span class="sp-pn-dim" data-busy={tl.busySeconds}>{t('sessions.page.panel.conv.busy', { time: busyWord(tl.busySeconds) })}</span>{/if}
                                {#if !codex && !gone}{#each tl.compacts as k (k.id)}<span class="sp-pn-dim" data-mark="compact">{t('sessions.page.panel.conv.compact', { date: dateWord(k.at) })}</span>{/each}{/if}
                            </div>
                        {/snippet}
                        {#snippet actions()}
                            {#if !c.current}
                                {#if c.transcript_on_disk}
                                    <Button size="sm" data-pn-act="resume" disabled={resuming !== null} onclick={() => onResume(c.conversation_id)}>{t('sessions.page.panel.conv.resume')}</Button>
                                {:else}
                                    <span class="sp-pn-gone">{t('sessions.page.panel.conv.gone')}</span>
                                {/if}
                            {/if}
                        {/snippet}
                    </ListRow>
                {/each}
            {/snippet}
        </List>
        {#if notice}<p class="sp-pn-note" role="status" data-error={notice.error ? '' : undefined}>{notice.text}</p>{/if}
    {/if}
</section>
