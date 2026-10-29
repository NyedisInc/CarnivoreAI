
<script lang="ts">
    import StatusLed from '../StatusLed.svelte';
    import Toolbar from '../base/Toolbar.svelte';
    import Button from '../base/Button.svelte';
    import IconButton from '../base/IconButton.svelte';
    import Select from '../base/Select.svelte';
    import type { Translate } from '../sessions/types';
    import ViewSwitch from './ViewSwitch.svelte';
    import type { SessionsView } from './views';
    import { PROJECT_SORTS, type ProjectSortKey } from './toolbar-prefs';
    import { STATE_KEYS, filtersActive, toggleState, NO_FILTERS, type Filters, type StateKey } from './filters';

    interface Props {
        view: SessionsView;
        onView: (next: SessionsView) => void;
        filters: Filters;
        companies: readonly string[];
        projects: readonly string[];
        computers: readonly string[];
        providers: readonly string[];
        projectSort: ProjectSortKey;
        onProjectSort: (next: ProjectSortKey) => void;
        shown: number;
        total: number;
        t: Translate;
    }
    let { view, onView, filters = $bindable(), companies, projects, computers, providers, projectSort, onProjectSort, shown, total, t }: Props = $props();

    let barWidth = $state(0);
    let phone = $state(false);
    function followBar(el: Element): (() => void) | undefined {
        if (typeof ResizeObserver === 'undefined') return undefined;
        const watch = new ResizeObserver(() => {
            barWidth = el.clientWidth;
            phone = window.innerWidth <= 700;
        });
        watch.observe(el);
        return () => watch.disconnect();
    }
    const compact = $derived(barWidth > 0 && barWidth < 960 && !phone);
    const active = $derived(filtersActive(filters));

    const selects = $derived([
        { key: 'company', options: companies },
        { key: 'project', options: projects },
        { key: 'computer', options: computers },
        { key: 'provider', options: providers },
    ] as const);

    const LED: Record<Exclude<StateKey, 'archived'>, string> = { working: 'working', questions: 'question', sleep: 'asleep', closed: 'dead' } as const;
    function flip(state: StateKey): void {
        filters.on = toggleState(filters.on, state);
    }
    function clear(): void {
        Object.assign(filters, NO_FILTERS);
    }
</script>


{#snippet facets()}
    <div class="sp-g" role="group" aria-label={t('sessions.page.filter.state')} data-g="state">
        <span class="sp-gl">{t('sessions.page.filter.state')}</span>
        <span class="sp-seg">
            {#each STATE_KEYS as state (state)}
                {@const name = t(`sessions.page.filter.state.${state}`)}
                {#if state === 'archived'}
                    <IconButton variant="quiet" data-state={state} pressed={filters.on.includes(state)} label={name} icon="archive" iconSize={14} onclick={() => flip(state)} />
                {:else}
                    <IconButton variant="quiet" data-state={state} pressed={filters.on.includes(state)} label={name} onclick={() => flip(state)}>
                        {#snippet children()}<StatusLed status={LED[state]} size="14px" />{/snippet}
                    </IconButton>
                {/if}
            {/each}
        </span>
    </div>
    {#each selects as sel (sel.key)}
        {@const label = t(`sessions.page.filter.${sel.key}`)}
        <div class="sp-g oc-focus-host" data-g={sel.key}>
            <span class="sp-gl">{label}</span>
            <Select size="sm" aria-label={label} bind:value={filters[sel.key]}
                options={[{ value: '', label: compact ? label : t('sessions.page.filter.any') }, ...sel.options.map((option) => ({ value: option, label: option }))]} />
        </div>
    {/each}
    <div class="sp-g oc-focus-host" data-g="sort">
        <span class="sp-gl">{t('sessions.page.sort.label')}</span>
        <Select size="sm" aria-label={t('sessions.page.sort.label')} value={projectSort} onchange={(e) => onProjectSort(e.currentTarget.value as ProjectSortKey)}
            options={PROJECT_SORTS.map((key) => ({ value: key, label: t(`sessions.page.sort.${key}`) }))} />
    </div>
{/snippet}

<Toolbar band class={compact ? 'sp-bar sp-bar--compact' : 'sp-bar'} filters={facets} label={t('sessions.page.filter.label')} {@attach followBar}>
    {#snippet end()}
        {#if active}<Button size="sm" data-clear onclick={clear}>{t('sessions.page.filter.clear')}</Button>{/if}
        <ViewSwitch {view} {onView} {t} />
        <span class="sp-count" aria-live="polite">{t('sessions.page.count', { shown, total })}</span>
    {/snippet}
</Toolbar>
