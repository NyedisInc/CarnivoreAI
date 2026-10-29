
<script lang="ts">
    import { untrack } from 'svelte';
    import Button from '../base/Button.svelte';
    import Field from '../base/Field.svelte';
    import type { PublishTab } from '../catalog/menu/route';
    import { forwardMenuKey, type PageRowMenu } from '../item-menu/page-row';
    import { tabKey, folderKey } from './keys';
    import { emptyKey } from './kinds';
    import KindMark from '../catalog/KindMark.svelte';
    import { isOpen, bucketKey, canWithdraw } from './stages';
    import { KIND_OF_TAB, KIND_TABS, effectiveSub, kindList, submissionGroups, type ItemRecord, type RowData, type TabStat } from './list-model';
    import { reduced } from './motion';
    import ListRow from './ListRow.svelte';
    import { rowMenuNodes, type RowMenuAction } from './row-menu-nodes';
    import StageKey from './StageKey.svelte';
    import type { PageProps } from './props';

    interface Props extends PageProps {
        records: ItemRecord[];
        stats: Record<PublishTab, TabStat>;
        flash: boolean;
    }
    const { store, actions, t, records, stats, flash }: Props = $props();

    const tab = $derived(store.tab);
    const query = $derived(store.filters[tab] ?? '');
    const onSubmissions = $derived(tab === 'submissions');
    const tabName = $derived(t(tabKey(tab)));
    const groups = $derived(onSubmissions ? submissionGroups(records, query, t) : []);
    const flat = $derived(tab === 'submissions' ? [] : kindList(records, tab, query));
    const rowCount = $derived(onSubmissions ? groups.reduce((n, g) => n + g.rows.length, 0) : flat.length);
    const loading = $derived((store.folders === null && !store.failure.folders) || (store.signedIn && store.mine === null && !store.failure.mine));
    const account = $derived(store.account);
    const handleLine = $derived(
        store.signedIn && account?.handle
            ? t(account.handle_status === 'pending' ? 'publish.page.strip.handle_line_pending' : 'publish.page.strip.handle_line_confirmed', { handle: account.handle })
            : '',
    );
    const selected = $derived(records.find((r) => r.location === store.sel) ?? null);
    const selectedSub = $derived(selected ? effectiveSub(selected, store.selSub) : null);

    const seen: Record<string, string> = {};
    let primed = false;
    let changed = $state<Record<string, boolean>>({});
    $effect(() => {
        const next: Record<string, boolean> = {};
        const mark = records.map((r) => [r.location, `${r.latest?.status ?? ''}/${r.latest?.gate_state ?? ''}/${r.phase}`] as const);
        untrack(() => {
            for (const [location, key] of mark) {
                if (primed && location in seen && seen[location] !== key && !reduced()) next[location] = true;
                seen[location] = key;
            }
            primed = true;
            if (Object.keys(next).length > 0) changed = { ...changed, ...next };
        });
    });

    function pick(row: RowData, action: RowMenuAction): void {
        const record = records.find((r) => r.location === row.location);
        store.select(row.location, row.subId);
        if (action === 'check') store.setWizard(0);
        if (action === 'withdraw' && record?.latest) store.askWithdraw(record.latest.id);
    }

    function menuOf(row: RowData, label: string): () => PageRowMenu | null {
        return () => {
            const record = records.find((r) => r.location === row.location);
            const latest = record?.latest ?? null;
            const nodes = rowMenuNodes({ canCheck: !(latest && isOpen(latest)), canWithdraw: !!latest && canWithdraw(latest) }, t, (action) => pick(row, action));
            return { type: 'pagerow', ctx: { label, nodes } };
        };
    }

    function isSelected(row: RowData): boolean {
        if (store.rulesOpen || row.location !== store.sel) return false;
        return onSubmissions ? row.subId === selectedSub : true;
    }

    function onKeydown(event: KeyboardEvent): void {
        const rows = [...(event.currentTarget as HTMLElement).querySelectorAll<HTMLElement>('.d-row')];
        const at = rows.indexOf(document.activeElement as HTMLElement);
        if (at < 0) return;
        if (forwardMenuKey(event, rows[at] ?? null)) return;
        if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
        event.preventDefault();
        rows[at + (event.key === 'ArrowDown' ? 1 : -1)]?.focus();
    }

    function rowLabel(row: RowData): string {
        return row.harness ? `${row.name} (${row.harness})` : row.name;
    }

    const foldersLine = $derived(
        store.foldersReason && tab !== 'submissions'
            ? t(`publish.page.failure.folders_${KIND_OF_TAB[tab]}`, { reason: store.foldersReason })
            : store.failure.folders,
    );

    const sameLine = $derived(!!store.failure.folders && !!store.failure.mine && foldersLine === store.failure.mine);

    const noneLine = $derived(
        tab === 'submissions' ? '' : tab === 'plugins'
            ? t(emptyKey('plugins'))
            : `${t(emptyKey(tab), { kind: KIND_OF_TAB[tab] })} ${t('publish.page.list.read_from', { folder: t(folderKey(KIND_OF_TAB[tab] as 'skill')) })}`,
    );
</script>

<aside class="d-list" class:pp-flash={flash} aria-label={t('publish.page.list.aside_aria')} data-pp="ListColumn">
    <div class="d-list__head"><span class="pl-label d-list__lab">{tabName}</span><span class="d-list__count">{stats[tab].count ?? ''}</span></div>
    <p class="d-handle">{handleLine}</p>
    <div class="d-filter">
        <Field
            type="search"
            autocomplete="off"
            value={query}
            placeholder={t('publish.page.list.search', { tab: tabName })}
            aria-label={t('publish.page.list.search', { tab: tabName })}
            oninput={(event) => store.setFilter(tab, event.currentTarget.value)}
        />
    </div>
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="d-groups" onkeydown={onKeydown}>
        {#if store.failure.folders}
            <div class="d-empty d-empty--fail" role="alert"><p>{foldersLine}</p><Button size="sm" onclick={() => void actions.refresh()}>{t('skill.action.retry')}</Button></div>
        {/if}
        {#if store.failure.mine && !sameLine}
            <div class="d-empty d-empty--fail" role="alert"><p>{store.failure.mine}</p><Button size="sm" onclick={() => void actions.refresh()}>{t('skill.action.retry')}</Button></div>
        {/if}
        {#if loading}
            <p class="d-empty" role="status">{t('publish.page.list.loading')}</p>
        {:else if records.length === 0 && !store.failure.folders && !store.failure.mine}
            <div class="d-empty">
                <p>{t('publish.page.list.nothing_found')}</p>
                {#each KIND_TABS as kindTab (kindTab)}<p><KindMark kind={KIND_OF_TAB[kindTab]} size="md" bare {t} /> {t('publish.page.list.reads_line', { kind: t(`skill.publish.kind.${KIND_OF_TAB[kindTab]}`), folder: t(folderKey(KIND_OF_TAB[kindTab] as 'skill')) })}</p>{/each}
            </div>
        {:else if onSubmissions}
            {#each groups as group (group.bucket)}
                <h3 class="pl-label d-grp">{t(bucketKey(group.bucket))}</h3>
                <ul>
                    {#each group.rows as row (row.key)}
                        {@const label = rowLabel(row)}
                        <ListRow {row} selected={isSelected(row)} changed={!!changed[row.location]} submissions {t} onPick={() => store.select(row.location, row.subId)} menu={menuOf(row, label)} onFlashEnd={() => { changed = { ...changed, [row.location]: false }; }} />
                    {/each}
                </ul>
            {/each}
            {#if rowCount === 0 && (stats.submissions.count ?? 0) > 0}
                <p class="d-empty">{t('publish.page.list.no_match', { q: query })}</p>
            {:else if stats.submissions.count === 0}
                <div class="d-empty"><p>{t('publish.page.list.nothing_sent')}</p><p>{t('publish.page.list.nothing_sent_lead')}</p></div>
            {/if}
        {:else if stats[tab].count === null}
            
        {:else if stats[tab].count === 0}
            <p class="d-empty">{noneLine}</p>
        {:else if rowCount === 0}
            <p class="d-empty">{t('publish.page.list.no_match', { q: query })}</p>
        {:else}
            <ul>
                {#each flat as row (row.key)}
                    {@const label = rowLabel(row)}
                    <ListRow {row} selected={isSelected(row)} changed={!!changed[row.location]} submissions={false} {t} onPick={() => store.select(row.location, null)} menu={menuOf(row, label)} onFlashEnd={() => { changed = { ...changed, [row.location]: false }; }} />
                {/each}
            </ul>
        {/if}
    </div>
    <StageKey {t} />
</aside>
