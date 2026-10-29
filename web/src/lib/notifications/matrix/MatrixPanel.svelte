
<script lang="ts">
    import { onMount } from 'svelte';
    import { t as reactiveT } from '../../i18n/index.svelte';
    import type { Translate } from '../../sessions/types';
    import { Select } from '../../base';
    import Check from '../../../opscenter/ui/Check.svelte';
    import '../../settings-page/panel-kit/panel-kit.css';
    import './matrix.css';
    import { SCREEN, type Fetcher } from './api';
    import { cellOf, DEFAULTS_COLUMN, destinationColumns, groupRows, lockReason, PHONE_QUERY } from './logic';
    import { attach, matrix, resetCell, setDefault, setTick } from './store.svelte';
    import MatrixCell from './MatrixCell.svelte';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = reactiveT, fetcher }: Props = $props();

    let phone = $state(false);
    let picked = $state(SCREEN);

    onMount(() => {
        const stop = attach(fetcher);
        const query = typeof window.matchMedia === 'function' ? window.matchMedia(PHONE_QUERY) : null;
        phone = query?.matches === true;
        const onChange = (event: MediaQueryListEvent): void => { phone = event.matches; };
        query?.addEventListener('change', onChange);
        return () => { stop(); query?.removeEventListener('change', onChange); };
    });

    const groups = $derived(groupRows(matrix.families, matrix.types));
    const columns = $derived(destinationColumns(matrix.settings));
    const colName = (id: string, name: string, kind: string): string => name || (kind === 'webpush' ? t('settings.notify.matrix.webpush_device', { id: id.slice(-4) }) : id);
    const typeLabel = (key: string): string => t(key);
    function columnTitle(column: string): string {
        if (column === SCREEN) return t('settings.notify.matrix.col.screen');
        if (column === DEFAULTS_COLUMN) return t('settings.notify.matrix.col.defaults');
        const c = columns.find((d) => d.id === column);
        return colName(column, c?.name ?? '', c?.kind ?? '');
    }
    const activeColumn = $derived(picked === SCREEN || picked === DEFAULTS_COLUMN || columns.some((c) => c.id === picked) ? picked : SCREEN);

    function cellFor(column: string, row: { id: string; defaults: { outside_locked_off: boolean } }) {
        if (column !== DEFAULTS_COLUMN) return cellOf(matrix.settings, column, row.id);
        const locked = row.defaults.outside_locked_off;
        return { value: !locked && matrix.settings.defaults[row.id] === true, source: locked ? ('locked' as const) : ('global' as const), locked };
    }

    const toggle = (column: string, typeId: string, next: boolean): Promise<void> =>
        column === DEFAULTS_COLUMN ? setDefault(typeId, next) : setTick(column, typeId, next);
</script>

<div class="tm" data-mx="matrix">
    <p class="tm__sub">{t('settings.notify.matrix.intro')}</p>
    <Check label={t('settings.notify.matrix.local_only')} hint={t('settings.notify.matrix.local_only.hint')} role="switch"
        checked={matrix.localOnly} data-mx="local-only" onToggle={(next) => (matrix.localOnly = next)} />
    {#if matrix.problem}<p class="tm__problem" role="alert" data-mx="problem">{matrix.problem}</p>{/if}

    {#if !matrix.loaded}
        <p class="tm__sub" data-mx="loading">{t('settings.notify.matrix.loading')}</p>
    {:else if phone}
        <div class="mx-picker" data-mx="phone">
            <label class="tm__sub" for="mx-column">{t('settings.notify.matrix.pick')}</label>
            <Select id="mx-column" bind:value={picked} data-mx="picker" options={[
                { value: SCREEN, label: t('settings.notify.matrix.col.screen') },
                { value: DEFAULTS_COLUMN, label: t('settings.notify.matrix.col.defaults') },
                ...columns.map((c) => ({ value: c.id, label: colName(c.id, c.name, c.kind) })),
            ]} />
            {#if activeColumn === DEFAULTS_COLUMN}<p class="tm__sub">{t('settings.notify.matrix.col.defaults.hint')}</p>{/if}
        </div>
        <div class="mx-list" data-mx="list">
            {#each groups as group (group.family.id)}
                <h4 class="mx-family-label" data-mx="family">{t(group.family.label_key)}</h4>
                {#each group.rows as row (row.id)}
                    <div class="mx-item" data-mx-row={row.id}>
                        <MatrixCell {t} cell={cellFor(activeColumn, row)} name={typeLabel(row.label_key)} label={typeLabel(row.label_key)}
                            why={lockReason(row, activeColumn === DEFAULTS_COLUMN ? 'outside' : activeColumn)} showSource={activeColumn !== DEFAULTS_COLUMN}
                            cellId={`${activeColumn}:${row.id}`} onToggle={(next) => void toggle(activeColumn, row.id, next)}
                            onReset={() => void resetCell(activeColumn, row.id)} />
                        <span class="mx-desc">{t(row.description_key)}</span>
                    </div>
                {/each}
            {/each}
        </div>
    {:else}
        <div class="mx-scroll" data-mx="desktop">
            <table class="mx-table">
                <thead>
                    <tr>
                        <th class="mx-type" scope="col">{t('settings.notify.matrix.col.type')}</th>
                        <th scope="col" data-mx-col={SCREEN}>{t('settings.notify.matrix.col.screen')}</th>
                        <th scope="col" data-mx-col={DEFAULTS_COLUMN}>
                            {t('settings.notify.matrix.col.defaults')}
                            <span class="mx-colsub">{t('settings.notify.matrix.col.defaults.hint')}</span>
                        </th>
                        {#each columns as c (c.id)}
                            <th scope="col" data-mx-col={c.id}>
                                <span class="mx-colname">{colName(c.id, c.name, c.kind)}</span>
                                {#if !c.enabled}<span class="mx-colsub">{t('settings.notify.matrix.off')}</span>{/if}
                            </th>
                        {/each}
                    </tr>
                </thead>
                <tbody>
                    {#each groups as group (group.family.id)}
                        <tr class="mx-family"><th colspan={3 + columns.length} scope="colgroup" data-mx="family">{t(group.family.label_key)}</th></tr>
                        {#each group.rows as row (row.id)}
                            <tr data-mx-row={row.id}>
                                <th class="mx-type" scope="row">
                                    <span class="mx-label">{t(row.label_key)}</span>
                                    <span class="mx-desc">{t(row.description_key)}{row.defaults.screen_surface === 'approvals_inbox' ? ' ' + t('settings.notify.matrix.inbox') : ''}</span>
                                </th>
                                {#each [SCREEN, DEFAULTS_COLUMN, ...columns.map((c) => c.id)] as column (column)}
                                    <td>
                                        <MatrixCell {t} cell={cellFor(column, row)} name={`${t(row.label_key)}, ${columnTitle(column)}`}
                                            why={lockReason(row, column === DEFAULTS_COLUMN ? 'outside' : column)} showSource={column !== DEFAULTS_COLUMN}
                                            cellId={`${column}:${row.id}`} onToggle={(next) => void toggle(column, row.id, next)}
                                            onReset={() => void resetCell(column, row.id)} />
                                    </td>
                                {/each}
                            </tr>
                        {/each}
                    {/each}
                </tbody>
            </table>
        </div>
    {/if}

    <ul class="mx-legend" data-mx="legend">
        <li>{t('settings.notify.matrix.lock.in_app')}</li>
        <li>{t('settings.notify.matrix.lock.health')}</li>
    </ul>
</div>
