
<script lang="ts">
    import { t as reactiveT } from '../../i18n/index.svelte';
    import type { Translate } from '../../sessions/types';
    import Button from '../../base/Button.svelte';
    import Field from '../../base/Field.svelte';
    import Fold from '../../base/Fold.svelte';
    import State from '../../base/State.svelte';
    import Switch from '../../base/Switch.svelte';
    import DataTable from '../../../opscenter/ui/DataTable.svelte';
    import Sparkline from '../../../opscenter/ui/Sparkline.svelte';
    import type { ColumnSpec } from '../../../opscenter/engine/types';
    import { errorText } from '../panel-kit/error-text';
    import { fetchToolSwitches, resetToolUsage, setToolSwitches, DEPRECATED_GROUP, type Fetcher, type ToolGroup, type ToolSwitch, type ToolSwitches } from './api';

    interface Props {
        t?: Translate;
        fetcher?: Fetcher;
    }
    const { t = reactiveT, fetcher }: Props = $props();

    const MIN_NAME_CH = 12;
    const NAME_STYLE = 'flex: none; white-space: nowrap; overflow: visible; text-overflow: clip';
    const TEXT_STYLE = 'flex: 0 1 auto; min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis';


    let held = $state<ToolSwitches | null>(null);
    let folded = $state<Record<string, boolean>>({});
    let query = $state('');
    let busy = $state(false);
    let problem = $state('');
    let resetDone = $state(false);

    const columns = $derived<ColumnSpec[]>([
        { key: 'tool', headKey: 'settings.mcp_tools.col.tool', minPx: 140, weight: 3, insetPx: 12,
            minCh: Math.max(MIN_NAME_CH, ...(held?.groups ?? []).flatMap((g) => g.tools.map((tool) => tool.name.length))) },
        { key: 'calls', headKey: 'settings.mcp_tools.col.calls', minPx: 48, weight: 0.01, align: 'end', minCh: 5 },
        { key: 'trend', headKey: 'settings.mcp_tools.col.trend', minPx: 72, weight: 0.01, align: 'end' },
        { key: 'on', headKey: 'settings.mcp_tools.col.on', minPx: 48, weight: 0.01, align: 'end', insetPx: 12 },
    ]);

    const groups = $derived<readonly ToolGroup[]>(held?.groups ?? []);
    const needle = $derived(query.trim().toLowerCase());

    function visible(group: ToolGroup): readonly ToolSwitch[] {
        if (!needle || group.group.toLowerCase().includes(needle)) return group.tools;
        return group.tools.filter((tool) => [tool.name, tool.description, tool.sub ?? '', tool.family ?? ''].some((text) => text.toLowerCase().includes(needle)));
    }

    function blocks(tools: readonly ToolSwitch[]): { sub: string; tools: ToolSwitch[] }[] {
        const out: { sub: string; tools: ToolSwitch[] }[] = [];
        for (const tool of tools) {
            const sub = tool.sub ?? '';
            const block = out.find((b) => b.sub === sub);
            if (block) block.tools.push(tool); else out.push({ sub, tools: [tool] });
        }
        return out.sort((a, b) => Number(b.sub === '') - Number(a.sub === ''));
    }

    const shownGroups = $derived(groups.map((group) => ({ group, tools: visible(group) })).filter((entry) => entry.tools.length > 0));

    const foldedByDefault = (name: string): boolean => name === DEPRECATED_GROUP;

    const isFolded = (name: string): boolean => folded[name] ?? foldedByDefault(name);

    const isOpen = (name: string): boolean => needle !== '' || !isFolded(name);

    function setAllOpen(expanded: boolean): void {
        folded = Object.fromEntries(groups.map((group) => [group.group, !expanded]));
    }
    const counted = $derived(held?.usage != null);
    const totalCalls = $derived(groups.reduce((sum, g) => sum + g.tools.reduce((n, tool) => n + (tool.calls ?? 0), 0), 0));

    const summary = $derived(!held ? '' : !counted ? t('settings.mcp_tools.no_counts')
        : t(held.usage?.since ? 'settings.mcp_tools.since' : 'settings.mcp_tools.since_never',
            { time: held.usage?.since ? new Date(held.usage.since).toLocaleString() : '', count: String(totalCalls) }));

    async function load(): Promise<void> {
        try {
            held = await fetchToolSwitches(fetcher);
        } catch (error) {
            problem = errorText(error);
        }
    }
    void load();

    async function run(action: () => Promise<ToolSwitches>): Promise<boolean> {
        busy = true;
        problem = '';
        try {
            held = await action();
            return true;
        } catch (error) {
            problem = errorText(error);
            await load();
            return false;
        } finally {
            busy = false;
        }
    }

    function write(set: Record<string, boolean>): Promise<boolean> {
        resetDone = false;
        return run(() => setToolSwitches(set, fetcher));
    }

    function setGroup(tools: readonly ToolSwitch[], wanted: boolean): Promise<boolean> {
        return write(Object.fromEntries(tools.map((tool) => [tool.name, wanted])));
    }

    async function resetCounts(): Promise<void> {
        resetDone = await run(() => resetToolUsage(fetcher));
    }
</script>

{#snippet cell(tool: ToolSwitch, column: ColumnSpec, _index: number)}
    {#if column.key === 'tool'}
        <span class="oc-rc-name">
            <bdi class="oc-rc-name-text" style={NAME_STYLE} data-mcp-name={tool.name}>{tool.name}</bdi>
            <span class="oc-rc-muted" style={TEXT_STYLE} title={tool.description} data-mcp-desc={tool.name}>{tool.description}</span>
            {#if tool.family_hidden}{@const note = t('settings.mcp_tools.family_hidden', { why: tool.hidden_because })}<span class="oc-rc-muted" style={TEXT_STYLE} title={note} data-mcp-hidden={tool.name}>{note}</span>{/if}
            {#if tool.alias_of}<span class="oc-rc-muted" style={NAME_STYLE} data-mcp-alias={tool.name}>{t('settings.mcp_tools.alias_of', { name: tool.alias_of })}</span>{/if}
            {#if !tool.default_enabled}<span class="oc-rc-muted" style={NAME_STYLE}>{t('settings.mcp_tools.default_off')}</span>{/if}
        </span>
    {:else if column.key === 'calls'}
        <span class="oc-rc-muted" data-mcp-calls={tool.name}>{tool.calls ?? '-'}</span>
    {:else if column.key === 'trend'}
        {#if tool.daily}<span data-mcp-trend={tool.name}><Sparkline values={[...tool.daily]} height={16} barWidth={6} /></span>{/if}
    {:else}
        <Switch label="" aria-label={tool.name} bind:checked={() => tool.enabled, (next) => void write({ [tool.name]: next })} disabled={busy} bare
            data-mcp-tool={tool.name} />
    {/if}
{/snippet}

<div class="mt" data-mcp-tools="panel">
    <div class="mt__bar mt__bar--split">
        <span class="oc-rc-line" data-mcp-tools="summary">{summary}</span>
        <span class="mt__bar">
            {#if resetDone}<span class="oc-rc-muted" role="status" data-mcp-tools="reset-done">{t('settings.mcp_tools.reset_done')}</span>{/if}
            <Button variant="danger" size="sm" disabled={busy || !counted} data-mcp-tools="reset"
                onclick={() => void resetCounts()}>{t('settings.mcp_tools.reset')}</Button>
        </span>
    </div>
    <div class="mt__bar" data-mcp-tools="filter-bar">
        <Field block type="search" data-mcp-tools="filter" bind:value={query}
            placeholder={t('settings.mcp_tools.filter_placeholder')} aria-label={t('settings.mcp_tools.filter_label')} />
        <Button size="sm" data-mcp-tools="expand-all" onclick={() => setAllOpen(true)}>{t('settings.mcp_tools.expand_all')}</Button>
        <Button size="sm" data-mcp-tools="fold-all" onclick={() => setAllOpen(false)}>{t('settings.mcp_tools.fold_all')}</Button>
    </div>
    {#if held}
        {#each shownGroups as entry (entry.group.group)}
            {@const group = entry.group}
            {@const on = group.tools.filter((tool) => tool.enabled).length}
            <section data-mcp-tools-group={group.group}>
                <Fold label={group.group} count={t('settings.mcp_tools.group_count', { on: String(on), total: String(group.tools.length) })}
                    bind:open={() => isOpen(group.group), (next) => (folded[group.group] = !next)}>
                    {#snippet actions()}
                        <Button size="sm" disabled={busy || entry.tools.every((tool) => tool.enabled)}
                            data-mcp-tools="all-on" onclick={() => void setGroup(entry.tools, true)}>{t('settings.mcp_tools.all_on')}</Button>
                        <Button size="sm" disabled={busy || entry.tools.every((tool) => !tool.enabled)}
                            data-mcp-tools="all-off" onclick={() => void setGroup(entry.tools, false)}>{t('settings.mcp_tools.all_off')}</Button>
                    {/snippet}
                    {#snippet children()}
                      {#if isOpen(group.group)}
                        {#if group.group === DEPRECATED_GROUP}<State kind="warn" inline title={t('settings.mcp_tools.deprecated_note')} data-mcp-tools="deprecated-note" />{/if}
                        {#each blocks(entry.tools) as block (block.sub)}
                            {#if block.sub !== ''}<p class="oc-label mt__sub" data-mcp-tools="sub" data-mcp-sub={block.sub}>{block.sub}</p>{/if}
                            <DataTable {columns} rows={[...block.tools]} rowHeight={30} headHeight={26}
                                rowKey={(tool) => tool.name} {cell} />
                        {/each}
                      {/if}
                    {/snippet}
                </Fold>
            </section>
        {/each}
        {#if shownGroups.length === 0}<State inline title={t('settings.mcp_tools.no_match')} data-mcp-tools="no-match" />{/if}
    {:else if !problem}
        <State kind="loading" inline title={t('settings.mcp_tools.loading')} />
    {/if}
    {#if problem}<State kind="error" inline title={problem} data-mcp-tools="problem" />{/if}
</div>

<style>
    .mt {
        display: flex;
        flex-direction: column;
        gap: var(--oc-space-3);
        width: 100%;
        min-width: 0;
    }

    .mt__bar {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: var(--oc-space-2);
        min-width: 0;
    }

    .mt__bar--split {
        justify-content: space-between;
    }

    .mt__bar :global([data-field]) {
        flex: 1 1 12rem;
    }

    .mt__sub {
        margin: var(--oc-space-2) 0 var(--oc-space-1);
    }
</style>
