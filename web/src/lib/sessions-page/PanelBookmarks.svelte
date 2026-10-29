
<script lang="ts">
    import type { BookmarkList } from '../bookmarks/api';
    import Button from '../base/Button.svelte';
    import Checkbox from '../base/Checkbox.svelte';
    import List from '../base/List.svelte';
    import ListRow from '../base/ListRow.svelte';
    import type { BookmarkWidgetActions } from '../../opscenter/cells/bookmarks/widget-actions.svelte';
    import type { Translate } from '../sessions/types';
    import { whenWord } from './panel-format';

    interface Props {
        list: BookmarkList | null;
        status: 'idle' | 'loading' | 'ready' | 'error';
        running: boolean;
        gone: boolean;
        claude: boolean;
        rowId: number;
        actions: BookmarkWidgetActions;
        t: Translate;
        now: number;
    }
    const { list, status, running, gone, claude, rowId, actions: marksActions, t, now }: Props = $props();

    const marks = $derived(list?.bookmarks ?? []);
</script>

<section class="sp-pn-sec" id="sp-pn-marks">
    <h3 class="pl-label">{t('sessions.page.panel.marks')}</h3>
    {#if !claude}
        <p class="sp-pn-note">{t('sessions.page.panel.marks.codex')}</p>
    {:else if status === 'error'}
        <p class="sp-pn-note">{t('sessions.page.panel.history_failed')}</p>
    {:else if status !== 'ready'}
        <p class="sp-pn-note">{t('sessions.page.loading')}</p>
    {:else if marks.length === 0}
        <p class="sp-pn-note">{t('sessions.page.panel.marks.none')}</p>
    {:else}
        {#if !gone}
            <div class="sp-pn-arm" title={running ? undefined : t('bookmarks.arm_not_live')}>
                <Checkbox tone="danger" label={t('bookmarks.arm')} bind:checked={marksActions.armed} disabled={!running} />
            </div>
        {/if}
        <List class="sp-pn-list" label={t('sessions.page.panel.marks')}>
            {#snippet children()}
                {#each marks as b (b.id)}
                    <ListRow wrap data-bm={b.id}>
                        {#snippet children()}
                            <div class="sp-pn-lt">
                                <span>{b.label || t('bookmarks.by_claude')}</span>
                                <span class="sp-pn-dim">{whenWord(b.entry_timestamp || b.created_at, now)}</span>
                                {#if b.snippet}<p class="sp-pn-snip">{b.snippet}</p>{/if}
                            </div>
                        {/snippet}
                        {#snippet actions()}
                            {#if gone}
                                <span class="sp-pn-gone">{t('sessions.page.panel.conv.gone')}</span>
                            {:else}
                                <Button size="sm" variant="danger" data-pn-act="rewind" disabled={!running || !marksActions.armed || marksActions.busy !== null} title={t('bookmarks.rewind')} onclick={() => void marksActions.rewind(rowId, { bookmarkId: b.id })}>{t('sessions.page.panel.marks.rewind')}</Button>
                                <Button size="sm" data-pn-act="branch" disabled={marksActions.busy !== null} title={t('bookmarks.branch')} onclick={() => void marksActions.branch(rowId, { bookmarkId: b.id })}>{t('sessions.page.panel.marks.branch')}</Button>
                            {/if}
                        {/snippet}
                    </ListRow>
                {/each}
            {/snippet}
        </List>
        {#if marksActions.notice}<p class="sp-pn-note" role="status" data-error={marksActions.notice.error ? '' : undefined}>{marksActions.notice.text}</p>{/if}
    {/if}
</section>
