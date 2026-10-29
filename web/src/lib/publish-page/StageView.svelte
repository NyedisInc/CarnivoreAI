
<script lang="ts">
    import Ident from './Ident.svelte';
    import { dateText, clockText } from './format';
    import { selectedRecord } from './item-model';
    import Panel from './Panel.svelte';
    import type { PageProps } from './props';
    import { timelineOf } from './side-data';
    import { stageKey } from './stages';
    import type { TlEntry } from './timeline-model';
    import './detail.css';
    import './side.css';

    const { store, t }: PageProps = $props();

    const rec = $derived(selectedRecord(store));
    const entry = $derived.by((): TlEntry | null => {
        if (!rec || !store.mid) return null;
        const found = timelineOf(store, rec, t, false).find((i) => i.kind === 'entry' && i.key === store.mid?.ev);
        return found && found.kind === 'entry' ? found : null;
    });
    const detail = $derived(entry?.detail ?? null);
    const row = $derived(detail ? (store.mine?.find((r) => r.id === detail.subId) ?? null) : null);
    const ident = $derived(row ? `${row.name.split('/').pop() ?? row.name} ${row.version}` : '');
</script>

<div class="pp-sv" data-pp="StageView">
    {#if entry && detail}
        <h2 class="d-name">{t(stageKey(detail.stage === 'approved' ? 'approved' : 'rejected'))}</h2>
        <p class="d-kind"><span class="pp-ident"><Ident text={ident} /></span><span>{dateText(entry.ts, t)} {clockText(entry.ts, t)}</span></p>
        {#if detail.stage === 'approved'}
            <Panel label={t('publish.page.stage_view.where_label')}>
                <p class="d-lead d-lead--first pp-ident"><Ident text={row && (row.status === 'published' || row.events.some((e) => e.what === 'published')) ? t('publish.page.stage_view.approved_live', { name: row.item_id || row.name, version: row.version }) : t('publish.page.stage_view.approved_now', { name: row?.name ?? '', version: row?.version ?? '' })} /></p>
            </Panel>
        {:else if detail.pulled}
            <Panel label={t('publish.page.stage_view.pulled_label')}><p class="d-lead d-lead--first pp-ident"><Ident text={detail.reason || t('publish.page.timeline.revoked.default_reason')} /></p></Panel>
            <Panel label={t('publish.page.stage_view.todo_label')}><p class="d-lead d-lead--first">{t('publish.page.stage_view.pulled_todo')}</p></Panel>
        {:else}
            <Panel label={t('publish.page.stage_view.reviewer_label')}><p class="d-lead d-lead--first pp-ident"><Ident text={detail.reason} /></p></Panel>
            {#if detail.left !== null}
                <Panel label={t('publish.page.stage_view.todo_label')}>
                    <p class="d-lead d-lead--first">{detail.left > 0 ? t('publish.page.stage_view.appeals_left', { count: detail.left }) : t('publish.page.stage_view.no_appeals')}</p>
                </Panel>
            {/if}
        {/if}
    {/if}
</div>
