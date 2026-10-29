
<script lang="ts">
    import Page from '../../opscenter/ui/Page.svelte';
    import Tabs, { panelAttrs, type TabDef } from '../../opscenter/ui/Tabs.svelte';
    import { readTab, writeTab } from '../../opscenter/ui/tab-memory';
    import { t } from '../i18n/index.svelte';
    import { openPluginsPage } from '../../cplugs/sdk';
    import { swarmInactive, setSwarmInactive } from '../../cplugs/huddle/huddle-swarm-inactive.svelte';
    import SwarmLedger from '../../cplugs/huddle/swarm/SwarmLedger.svelte';
    import SwarmOrg from '../../cplugs/huddle/swarm/SwarmOrg.svelte';
    import SwarmPanel from '../../cplugs/huddle/swarm/SwarmPanel.svelte';
    import SwarmSeatRefusal from '../../cplugs/huddle/swarm/SwarmSeatRefusal.svelte';
    import SwarmBoard from '../swarm-board/SwarmBoard.svelte';
    import { boardFocus, isFresh } from '../swarm-board/board-focus.svelte';
    import { lineageFloor, type FloorItem, type FloorTarget } from '../../cplugs/huddle/swarm/floor';
    import { SWARM_TABS, SWARM_TAB_KEY } from '../../cplugs/huddle/swarm/swarm-page';
    import { createSwarmLive, openFloorTarget, turnOnSeat } from '../../cplugs/huddle/swarm/swarm-live.svelte';
    import { swarmSettings } from '../../cplugs/huddle/swarm/swarm-settings.svelte';
    import { saveTierOrder } from '../../cplugs/huddle/swarm/node-order.svelte';
    import { turnOnRefusal } from '../../cplugs/huddle/swarm/turn-on-refusal';
    import { buildTree, floorItems } from '../../cplugs/huddle/swarm/swarm-tree';
    import { filterKey, toggleFilter } from '../../cplugs/huddle/agents/agent-page.svelte';

    interface Props {
        close?: () => void;
        embedded?: boolean;
    }
    const { close, embedded = false }: Props = $props();

    const live = createSwarmLive();
    const filtered = $derived(filterKey());
    const floor = $derived(lineageFloor(live.floor, filtered));

    function filterTo(item: FloorItem): void {
        toggleFilter(item.key, item.target.kind === 'agent' ? item.target.agentId : null);
    }
    const tree = $derived(buildTree(floor));

    let chosen = $state(readTab(SWARM_TAB_KEY, SWARM_TABS, ''));
    const tab = $derived(chosen || swarmSettings.page_default_view);
    $effect(() => {
        if (isFresh(boardFocus.request)) chosen = 'board';
    });
    const tabs = $derived<TabDef[]>(SWARM_TABS.map((id) => ({ id, label: t(`cplug.huddle.swarm.page.tab.${id}`) })));

    function pick(id: string): void {
        if (!(SWARM_TABS as readonly string[]).includes(id)) return;
        chosen = id;
        failed = null;
        refusal = '';
        writeTab(SWARM_TAB_KEY, id);
    }

    let turningOn = $state<string | null>(null);
    let failed = $state<string | null>(null);
    let refusal = $state('');
    const seat = $derived(floorItems(floor).find((i) => i.key === failed && i.target.kind === 'turn_on') ?? null);

    function open(target: FloorTarget, terminal = false): void {
        if (target.kind !== 'turn_on') return go(target, terminal);
        void turnOn(target);
    }

    function go(target: FloorTarget, terminal = false): void {
        openFloorTarget(target, terminal);
        if (terminal || target.kind !== 'agent') close?.();
    }

    async function turnOn(target: Extract<FloorTarget, { kind: 'turn_on' }>): Promise<void> {
        const item = floorItems(floor).find((i) => i.target === target);
        if (!item || turningOn !== null) return;
        turningOn = item.key;
        failed = null;
        refusal = '';
        try {
            await turnOnSeat(target);
        } catch (error) {
            refusal = turnOnRefusal(error, item.label);
            failed = item.key;
        } finally {
            turningOn = null;
        }
    }

    const showToggle = $derived(tab !== 'squares' && tab !== 'board' && (swarmInactive.shown || live.floor.inactive > 0));
</script>

{#snippet inactiveToggle()}
    <button type="button" class="pkg-toggle" data-swarm-toggle-inactive aria-pressed={swarmInactive.shown} onclick={() => setSwarmInactive(!swarmInactive.shown)}>
        {swarmInactive.shown ? t('cplug.huddle.swarm.inactive.hide') : t('cplug.huddle.swarm.inactive.show', { n: live.floor.inactive })}
    </button>
{/snippet}

{#snippet tabStrip()}
    <Tabs {tabs} active={tab} onSelect={pick} label={t('cplug.huddle.swarm.page.tabs')} idBase="swarm" />
{/snippet}

{#snippet notes()}
    {#if live.threadsReady === false}
        <div class="pkg-need" data-swarm-needs-permission>
            <span class="pkg-need-text">{t('cplug.huddle.swarm.need_permission')}</span>
            <button type="button" class="modal-btn modal-btn-secondary" data-swarm-open-plugins onclick={() => void openPluginsPage()}>{t('cplug.huddle.swarm.need_permission.open')}</button>
        </div>
    {/if}
{/snippet}

<Page title={t('cplug.huddle.swarm.page.title')} onClose={close} {embedded} tabs={tabStrip} notes={live.threadsReady === false ? notes : undefined}>
    <div class="pkg-body" class:pkg-body--scroll={tab === 'board'} data-swarm-page data-swarm-tab={tab} {...panelAttrs('swarm', tab)}>
        {#if tab === 'board'}
            <SwarmBoard />
        {:else}
            {#if tab === 'tree'}
                <SwarmLedger {tree} agents={live.agents} colors={live.colors} now={live.now} pack={live.pack} busy={turningOn} onOpen={open} />
            {:else if tab === 'org'}
                <SwarmOrg {tree} agents={live.agents} colors={live.colors} now={live.now} pack={live.pack} busy={turningOn} onOpen={(target) => open(target)} onFilter={filterTo} {filtered} foot={showToggle ? inactiveToggle : undefined} />
            {:else}
                <SwarmPanel flow {floor} agents={live.agents} colors={live.colors} density="expanded" now={live.now} pack={live.pack} onOpen={(target) => go(target)}
                           onFilter={filterTo} {filtered} onTurnOn={turnOnSeat} showInactive={swarmInactive.shown} onToggleInactive={() => setSwarmInactive(!swarmInactive.shown)}
                           onReorder={(tier, keys) => void saveTierOrder(tier, floor[tier], keys)} />
            {/if}
            {#if seat && refusal && tab !== 'squares'}
                <SwarmSeatRefusal text={refusal} />
            {/if}
            {#if showToggle}
                {#if tab !== 'org'}<div class="pkg-foot">{@render inactiveToggle()}</div>{/if}
            {/if}
        {/if}
    </div>
</Page>

<style>
  @layer components {
    .pkg-body {
        padding: var(--oc-space-3);
        min-width: 0;
    }

    /* the page frame */
    .pkg-body--scroll {
        flex: 1;
        min-height: 0;
        overflow-y: auto;
    }

    .pkg-need {
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 8px;
        padding: var(--oc-space-1) var(--oc-space-3);
        color: var(--oc-text-secondary);
        font-family: var(--font-mono);
        font-size: var(--oc-fs-label);
    }

    .pkg-need-text {
        flex: 1 1 16em;
        min-width: 0;
    }

    .pkg-need button {
        padding: 4px 10px;
        font-size: var(--oc-fs-label);
    }

    .pkg-foot {
        margin-top: var(--oc-space-3);
    }

    .pkg-toggle {
        padding: 0;
        border: 0;
        background: none;
        color: var(--oc-text-muted);
        font: inherit;
        font-family: var(--font-mono);
        font-size: var(--oc-fs-micro);
        text-decoration: underline;
        text-underline-offset: 2px;
        cursor: pointer;
    }

    .pkg-toggle:hover {
        color: var(--oc-text-bright);
    }
  }
</style>
