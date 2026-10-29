
<script lang="ts">
    import { onMount } from 'svelte';
    import { t as reactiveT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import '../settings-page/panel-kit/panel-kit.css';
    import './byoai.css';
    import { errorText } from '../settings-page/panel-kit/error-text';
    import { resourcePush } from '../resource-push/boot';
    import { fetchCallsPage, fetchCallsSummary, type CallFilters, type CallRow, type CallsPage, type CallsSummary, type Fetcher } from './api';
    import { costText, dayKey, dayLabel, firstLine, latencyText, modelName, tokensText } from './calls-logic';
    import Button from '../base/Button.svelte';
    import Segmented from '../base/Segmented.svelte';
    import Select from '../base/Select.svelte';
    import State from '../base/State.svelte';
    import CallsSummaryView from './CallsSummary.svelte';
    import { ai, attach } from './store.svelte';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = reactiveT, fetcher }: Props = $props();

    const TOPIC = 'ai_calls';
    const FALLBACK_MS = 10_000;
    const PAGE = 50;
    const RANGES: CallFilters['range'][] = ['24h', '7d', '30d'];
    const RESULTS: CallFilters['result'][] = ['', 'ok', 'error'];
    const BLANK: CallFilters = { range: '24h', feature: '', connection: '', model: '', result: '' };

    let filters = $state<CallFilters>({ ...BLANK });
    let page = $state<CallsPage | null>(null);
    let summary = $state<CallsSummary | null>(null);
    let problem = $state('');
    let open = $state<number | null>(null);
    let fresh = $state<Set<number>>(new Set());
    let seenLatest = $state(0);
    let behind = $state(0);
    let cursor: { before?: number; after?: number } = {};

    const following = $derived(page !== null && page.prev === null && !filters.feature && !filters.connection && !filters.model && !filters.result);
    const filtered = $derived(!!(filters.feature || filters.connection || filters.model || filters.result));

    const connectionName = (id: string | null): string => (id ? ai.config?.connections.find((c) => c.id === id)?.label || id : '');
    function featureName(id: string | null): string {
        if (!id) return t('settings.ai.calls.nofeature');
        const registered = ai.features.find((f) => f.id === id)?.label_key;
        for (const key of [registered, `ai.feature.${id.replace(/[^a-z0-9]+/gi, '_')}`]) {
            if (key && t(key) !== key) return t(key);
        }
        return id;
    }

    async function load(next: { before?: number; after?: number } = cursor, opts: { quiet?: boolean } = {}): Promise<void> {
        try {
            const [got, sum] = await Promise.all([fetchCallsPage(filters, PAGE, next, fetcher), fetchCallsSummary(filters.range, fetcher)]);
            const known = new Set(page?.calls.map((c) => c.id));
            fresh = opts.quiet && following && known.size ? new Set(got.calls.filter((c) => !known.has(c.id)).map((c) => c.id)) : new Set();
            cursor = next;
            page = got;
            summary = sum;
            seenLatest = got.latest;
            behind = 0;
            problem = '';
        } catch (error) {
            problem = errorText(error);
        }
    }

    async function onPush(): Promise<void> {
        if (following) return load(cursor, { quiet: true });
        try {
            const head = await fetchCallsPage(BLANK, 1, {}, fetcher);
            behind = Math.max(0, head.latest - seenLatest);
        } catch (error) {
            problem = errorText(error);
        }
    }

    function setFilter(patch: Partial<CallFilters>): void {
        filters = { ...filters, ...patch };
        open = null;
        void load({});
    }
    const clearAll = (): void => setFilter({ feature: '', connection: '', model: '', result: '' });
    const goFirst = (): void => { void load({}); };

    onMount(() => {
        const detach = attach(fetcher);
        void load({});
        const stopPush = resourcePush().pushOrPoll(() => void onPush(), FALLBACK_MS, [TOPIC]);
        return () => {
            stopPush();
            detach();
        };
    });

    const days = $derived.by(() => {
        const out: { key: string; label: string; rows: CallRow[] }[] = [];
        for (const row of page?.calls ?? []) {
            const key = dayKey(row.ts);
            if (out.at(-1)?.key !== key) out.push({ key, label: dayLabel(row.ts, t('settings.ai.calls.today'), t('settings.ai.calls.yesterday')), rows: [] });
            out.at(-1)!.rows.push(row);
        }
        return out;
    });
    const timeText = (ts: number): string => new Date(ts * 1000).toLocaleTimeString([], { hour12: false });
    const stampText = (ts: number): string => `${new Date(ts * 1000).toLocaleDateString()} ${timeText(ts)}`;
    const tokens = (row: CallRow): string => tokensText(row.input_tokens, row.output_tokens, t('settings.ai.calls.in'), t('settings.ai.calls.out'));
    const last = $derived(page ? page.start + page.calls.length - 1 : 0);
</script>

<div class="tm ai-calls" data-ai="calls">
    {#if summary}
        <div class="ai-bar" role="group" aria-label={t('settings.ai.calls.range')}>
            <Segmented label={t('settings.ai.calls.range')} value={filters.range} onchange={(r) => setFilter({ range: r as CallFilters['range'] })}
                options={RANGES.map((r) => ({ value: r, label: r, attrs: { 'data-ai-range': r } }))} />
        </div>
        <CallsSummaryView {t} {summary} {featureName} onpick={(kind, key) => setFilter({ [kind]: key })} />

        <div class="ai-bar" role="group" aria-label={t('settings.ai.calls.filters')}>
            <Select aria-label={t('settings.ai.calls.col.feature')} data-ai-filter="feature" value={filters.feature}
                onchange={(e) => setFilter({ feature: e.currentTarget.value })}
                options={[{ value: '', label: t('settings.ai.calls.all.feature') }, ...summary.options.feature.map((id) => ({ value: id, label: featureName(id) }))]} />
            <Select aria-label={t('settings.ai.calls.col.connection')} data-ai-filter="connection" value={filters.connection}
                onchange={(e) => setFilter({ connection: e.currentTarget.value })}
                options={[{ value: '', label: t('settings.ai.calls.all.connection') }, ...summary.options.connection.map((id) => ({ value: id, label: connectionName(id) }))]} />
            <Select aria-label={t('settings.ai.calls.col.model')} data-ai-filter="model" value={filters.model}
                onchange={(e) => setFilter({ model: e.currentTarget.value })}
                options={[{ value: '', label: t('settings.ai.calls.all.model') }, ...summary.options.model.map((id) => ({ value: id, label: modelName(id).name }))]} />
            <Segmented label={t('settings.ai.calls.col.ok')} value={filters.result} onchange={(r) => setFilter({ result: r as CallFilters['result'] })}
                options={RESULTS.map((r) => ({ value: r, label: t(`settings.ai.calls.result.${r || 'all'}`), attrs: { 'data-ai-result': r || 'all' } }))} />
            {#if filtered}<Button data-ai="calls-clear" onclick={clearAll}>{t('settings.ai.calls.clear')}</Button>{/if}
        </div>
    {/if}

    {#if behind > 0}
        <Button size="sm" data-ai="calls-new" onclick={goFirst}>{t('settings.ai.calls.new', { n: behind })}</Button>
    {/if}

    {#if page && page.calls.length > 0}
        <div class="ai-log" data-ai="calls-log">
            <div class="ai-row ai-row--head" aria-hidden="true">
                <span>{t('settings.ai.calls.col.ts')}</span><span>{t('settings.ai.calls.col.feature')}</span><span>{t('settings.ai.calls.col.connection')}</span>
                <span>{t('settings.ai.calls.col.model')}</span><span>{t('settings.ai.calls.col.ok')}</span><span class="ai-end">{t('settings.ai.calls.col.latency')}</span>
                <span class="ai-end">{t('settings.ai.calls.col.tokens')}</span><span class="ai-end">{t('settings.ai.calls.col.cost')}</span>
            </div>
            {#each days as day (`${day.key}:${day.rows[0]!.id}`)}
                <h4 class="ai-day">{day.label}</h4>
                {#each day.rows as row (row.id)}
                    {@const model = modelName(row.model)}
                    <div class="ai-entry" class:ai-entry--fresh={fresh.has(row.id)} data-ai-call={row.id}>
                        <Button variant="row" data-ai="call-row" aria-expanded={open === row.id} onclick={() => (open = open === row.id ? null : row.id)}>
                            <span class="ai-c ai-c--ts" data-ai-cell="ts">{timeText(row.ts)}</span>
                            <span class="ai-c ai-c--feature" data-ai-cell="feature">{featureName(row.feature)}</span>
                            <span class="ai-c ai-c--conn" data-ai-cell="connection">{connectionName(row.connection_id)}</span>
                            <span class="ai-c ai-c--model" data-ai-cell="model">{model.name}{#if model.provider}<span class="ai-sub">{model.provider}</span>{/if}</span>
                            <span class="ai-c ai-c--ok" data-ai-cell="ok" data-ok={String(!!row.ok)}><i class="ai-dot" aria-hidden="true"></i>{row.ok ? t('settings.ai.calls.ok') : t('settings.ai.calls.failed')}</span>
                            <span class="ai-c ai-c--lat ai-end" data-ai-cell="latency">{latencyText(row.latency_ms)}</span>
                            <span class="ai-c ai-c--tok ai-end" data-ai-cell="tokens">{tokens(row)}</span>
                            <span class="ai-c ai-c--cost ai-end" data-ai-cell="cost">{costText(row.cost_usd)}</span>
                            {#if !row.ok && row.error}<span class="ai-c ai-err" data-ai-cell="error">{firstLine(row.error)}</span>{/if}
                        </Button>
                        {#if open === row.id}
                            <dl class="ai-detail" data-ai="calls-detail">
                                {#each [
                                    ['feature', row.feature ?? '-'], ['capability', row.capability], ['model', row.model ?? '-'], ['connection', `${connectionName(row.connection_id)} ${row.connection_id ?? ''}`.trim() || '-'],
                                    ['time', stampText(row.ts)], ['tokens', tokens(row)], ['cost', costText(row.cost_usd)], ['latency', latencyText(row.latency_ms)], ['id', String(row.id)],
                                ] as const as [key, value] (key)}
                                    <div><dt>{t(`settings.ai.calls.detail.${key}`)}</dt><dd>{value}</dd></div>
                                {/each}
                                {#if row.error}<div class="ai-detail__err"><dt>{t('settings.ai.calls.col.error')}</dt><dd>{row.error}</dd></div>{/if}
                            </dl>
                        {/if}
                    </div>
                {/each}
            {/each}
        </div>
        <div class="ai-pager" data-ai="calls-pager">
            <span class="tm__sub" data-ai="calls-count">{t('settings.ai.calls.range_of', { from: page.start.toLocaleString(), to: last.toLocaleString(), total: page.total.toLocaleString() })}</span>
            <span class="ai-pager__btns">
                <Button data-ai="calls-newer" disabled={page.prev === null} onclick={() => void load({ after: page!.prev! })}>{t('settings.ai.calls.newer')}</Button>
                <Button data-ai="calls-older" disabled={page.next === null} onclick={() => void load({ before: page!.next! })}>{t('settings.ai.calls.older')}</Button>
            </span>
        </div>
    {:else if page}
        <p class="tm__sub" data-ai="calls-none">{t(filtered ? 'settings.ai.calls.none_filtered' : 'settings.ai.calls.none')}</p>
    {:else if !problem}
        <p class="tm__sub">{t('settings.ai.loading')}</p>
    {/if}
    {#if problem}<State kind="error" inline title={problem} data-ai="problem" />{/if}
</div>
