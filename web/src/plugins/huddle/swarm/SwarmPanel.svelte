<script lang="ts">
  import { Icon, LimitGauge, TaskMark } from '../../sdk/ui';
  import { providerMark, t, workingOnText } from '../../sdk';
  import type { ListingRow } from '../../sdk';
  import { colorBook, type ColorBook } from './agent-colors.svelte';
  import { Character, type CharacterPack, DEFAULT_PACK } from './characters';
  import type { Floor, FloorItem, FloorTarget } from './floor';
  import {
    columnsOf, contextScale, partsOf, seedOf, sizeOf, subSeeds, talkingSide,
    type PanelAgent, type PanelDensity,
  } from './panel-state';
  import { turnOnRefusal } from './turn-on-refusal';
  import { backgroundFor, colorFor, markRankOf, shapeFor, stateFor, sendFor } from './node-look';
  import { tierDrag } from './tier-drag';
  import type { OrderTier } from './node-order.svelte';
  import NodeMenu from './NodeMenu.svelte';
  import { nodeHold } from './node-menu';

  type TurnOn = Extract<FloorTarget, { kind: 'turn_on' }>;

  interface Props {
    floor: Floor;
    agents: readonly PanelAgent[];
    density: PanelDensity;
    now: number;
    pack?: CharacterPack;
    colors?: ColorBook;
    still?: boolean;
    showInactive: boolean;
    onToggleInactive: () => void;
    onOpen: (target: FloorTarget, terminal?: boolean) => void;
    onTurnOn?: (target: TurnOn) => Promise<unknown> | void;
    threadsReady?: boolean | null;
    onOpenPlugins?: () => void;
    flow?: boolean;
    onFilter?: (item: FloorItem) => void;
    filtered?: string | null;
    onReorder?: (tier: OrderTier, keys: string[]) => void;
    onHold?: (key: string, x: number, y: number) => void;
  }
  let { floor, agents, density, now, pack = DEFAULT_PACK, colors, still, showInactive, onToggleInactive, onOpen, onTurnOn, threadsReady = null, onOpenPlugins, flow = false, onFilter, filtered = null, onReorder, onHold }: Props = $props();

  const dragOf = (tier: OrderTier) => ({
    onReorder: onReorder ? (keys: string[]) => onReorder(tier, keys) : undefined,
    onHold: onReorder ? (key: string, x: number, y: number) => { holdOn(tier, key); onHold?.(key, x, y); } : undefined,
  });
  let root = $state<HTMLElement | undefined>();
  function holdOn(tier: OrderTier, key: string): void {
    const it = floor[tier].find((i) => i.key === key);
    const el = root?.querySelector<HTMLElement>(`[data-swarm-key="${CSS.escape(key)}"]`);
    if (it && el) openMenu(it, el);
  }
  function holdSquare(it: FloorItem, el: HTMLElement): void {
    if (onReorder && it !== floor.alpha) return;
    openMenu(it, el);
  }
  const book = $derived(colors ?? colorBook(agents, null));

  const parts = $derived(partsOf(density));

  let turningOn = $state<string | null>(null);
  let failed = $state<string | null>(null);
  let refusal = $state('');
  const seat = $derived.by((): FloorItem | null => floor.seats.find((i) => i.key === failed) ?? null);
  let picking = $state<'company' | 'project' | null>(null);

  function seatsOf(scope: 'company' | 'project'): FloorItem[] {
    return floor.seats.filter((i) => i.target.kind === 'turn_on' && i.target.scope === scope);
  }

  function openSlot(scope: 'company' | 'project'): void {
    const seats = seatsOf(scope);
    if (seats[0] && seats.length === 1) { picking = null; void turnOn(seats[0]); } else picking = picking === scope ? null : scope;
  }

  function choose(item: FloorItem): void {
    picking = null;
    void turnOn(item);
  }

  function press(item: FloorItem, event?: MouseEvent): void {
    if (onFilter && event?.shiftKey) return onFilter(item);
    if (item.target.kind === 'turn_on') void turnOn(item);
    else onOpen(item.target, event?.shiftKey === true);
  }

  function key(item: FloorItem, event: KeyboardEvent): void {
    if (!onFilter || event.key !== 'Enter' || !event.shiftKey) return;
    event.preventDefault();
    onFilter(item);
  }

  function down(event: MouseEvent): void {
    if (onFilter && event.shiftKey) event.preventDefault();
  }

  async function turnOn(item: FloorItem): Promise<void> {
    const target = item.target;
    if (target.kind !== 'turn_on' || turningOn !== null) return;
    turningOn = item.key;
    failed = null;
    refusal = '';
    try {
      await onTurnOn?.(target);
    } catch (error) {
      refusal = turnOnRefusal(error, item.label);
      failed = item.key;
    } finally {
      turningOn = null;
    }
  }

  function lineOf(row: ListingRow | undefined, agent: PanelAgent): string {
    return (row ? workingOnText(row) : '') || agent.job || '';
  }
  let menu = $state<{ item: FloorItem; anchor: HTMLElement } | null>(null);
  function openMenu(item: FloorItem, anchor: HTMLElement): void {
    if (item.ordinary || item.vacant || !item.agent) return;
    menu = { item, anchor };
  }
  function contextMenu(item: FloorItem, event: MouseEvent): void {
    if (item.ordinary || item.vacant || !item.agent) return;
    event.preventDefault();
    openMenu(item, event.currentTarget as HTMLElement);
  }
</script>

{#snippet item(it: FloorItem)}
  {#if it.vacant}
    <button type="button" class="pkp-it pkp-it--vacant" data-swarm-key={it.key} data-swarm-vacant={it.target.kind === 'turn_on' ? it.target.scope : undefined}
            data-swarm-active={it.active} aria-busy={turningOn === it.key ? 'true' : undefined} aria-current={filtered === it.key ? 'true' : undefined}
            title={t('cplug.huddle.swarm.seat.title', { name: it.label })} onclick={(e) => press(it, e)} onkeydown={(e) => key(it, e)} onmousedown={down}>
      <span class="pkp-sq pkp-seat" data-swarm-roll={it.rollup} style:--pkp-s="{sizeOf(it.rank, density, !flow)}px"></span>
      {#if parts.name}
        <span class="pkp-tx"><span class="pkp-l1"><b class="pkp-nm">{it.label}</b></span>
          {#if parts.workingOn}<span class="pkp-wo">{t('cplug.huddle.swarm.seat.vacant')}</span>{/if}</span>
      {/if}
    </button>
  {:else if it.agent}
    {@const agent = it.agent}
    {@const row = it.row}
    {@const state = stateFor(it, now)}
    {@const mark = parts.provider ? providerMark(agent.harness ?? null, 12) : null}
    {@const pct = row?.running_context_used_pct}
    <button type="button" class="pkp-it" data-swarm-key={it.key} data-swarm-agent={it.ordinary ? undefined : agent.id}
            data-swarm-session={it.ordinary ? it.session?.key : undefined} data-swarm-rank={it.rank}
            data-swarm-state={state} data-swarm-active={it.active} aria-current={filtered === it.key ? 'true' : undefined}
            title={t('cplug.huddle.agents.open', { name: it.label })} onclick={(e) => press(it, e)} onkeydown={(e) => key(it, e)} onmousedown={down}
            oncontextmenu={(e) => contextMenu(it, e)} use:nodeHold={(el) => holdSquare(it, el)}>
      <span class="pkp-sq" style:--pkp-s="{sizeOf(it.rank, density, !flow)}px">
        <Character {state} size={sizeOf(it.rank, density, !flow)} seed={seedOf(agent)} color={colorFor(book, it)}
                   subs={it.ordinary ? [] : subSeeds(agent, agents)} side={talkingSide(agent, agents, now)}
                   tell={sendFor(it)} {pack} {still} rank={agent.rank} shape={shapeFor(it)} background={backgroundFor(it)} label={it.label} />
      </span>
      {#if parts.name}
        <span class="pkp-tx">
          <span class="pkp-l1">
            <b class="pkp-nm"><TaskMark rank={markRankOf(it)} />{it.label}</b>
            {#if mark}
              <span class="pkp-prov" title={mark.label} data-swarm-provider={mark.key}>{#if mark.svg}{@html mark.svg}{:else}{mark.label}{/if}</span>
            {/if}
          </span>
          {#if parts.context}
            {#if typeof pct === 'number'}
              <LimitGauge variant="fill" pct={pct} scale={contextScale(pct)} height={2} meterText={t('cplug.huddle.swarm.context', { pct: Math.round(pct) })} />
            {:else}
              <LimitGauge variant="fill" pct={null} scale={null} height={2} meterText={t('cplug.huddle.swarm.context.none')} />
            {/if}
          {/if}
          {#if parts.workingOn}<span class="pkp-wo" data-swarm-working-on>{lineOf(row, agent)}</span>{/if}
        </span>
      {/if}
    </button>
  {/if}
{/snippet}

{#snippet slot(scope: 'company' | 'project')}
  {#if seatsOf(scope).length}
    <button type="button" class="pkp-it pkp-it--vacant" data-swarm-slot={scope} aria-expanded={picking === scope}
            title={t(`cplug.huddle.swarm.slot.${scope}`)} aria-label={t(`cplug.huddle.swarm.slot.${scope}`)} onclick={() => openSlot(scope)}>
      <span class="pkp-sq pkp-seat" style:--pkp-s="{sizeOf(scope, density)}px"><Icon name="plus" size={12} /></span>
      {#if parts.list}<span class="pkp-tx"><span class="pkp-l1"><b class="pkp-nm">{t(`cplug.huddle.swarm.slot.${scope}`)}</b></span></span>{/if}
    </button>
  {/if}
{/snippet}

{#snippet pick(scope: 'company' | 'project')}
  {#if picking === scope}
    <div class="pkp-ask" data-swarm-pick role="group" aria-label={t('cplug.huddle.swarm.slot.pick')}>
      <span class="pkp-ask-text">{t('cplug.huddle.swarm.slot.pick')}</span>
      <span class="pkp-pick-list">
        {#each seatsOf(scope) as it (it.key)}
          <button type="button" class="oc-btn oc-btn--sm" data-swarm-pick-seat={it.key} onclick={() => choose(it)}>{it.label}</button>
        {/each}
      </span>
    </div>
  {/if}
{/snippet}

{#snippet divider(label: string, count: number)}
  <div class="pkp-div"><span class="pkp-label">{label}</span><span class="pkp-count">{count}</span></div>
{/snippet}

{#snippet refused(scope: 'project' | 'company')}
  {#if seat && refusal && seat.target.kind === 'turn_on' && seat.target.scope === scope}
    <div class="pkp-ask"><span class="pkp-ask-text" data-swarm-refusal role="status">{refusal}</span></div>
  {/if}
{/snippet}

<div class="pkp" bind:this={root} data-swarm-panel data-density={density} data-flow={flow ? '' : undefined}>
  {#if threadsReady === false}
    <div class="pkp-need" data-swarm-needs-permission>
      <span class="pkp-need-text">{t('cplug.huddle.swarm.need_permission')}</span>
      {#if onOpenPlugins}
        <button type="button" class="oc-btn oc-btn--sm" data-swarm-open-plugins onclick={onOpenPlugins}>{t('cplug.huddle.swarm.need_permission.open')}</button>
      {/if}
    </div>
  {/if}

  {#if floor.alpha}
    <div class="pkp-alpha" data-swarm-section="alpha">
      {#if flow}{@render divider(t('cplug.huddle.swarm.section.alpha'), 1)}{/if}
      {@render item(floor.alpha)}
    </div>
  {/if}

  {#if floor.companies.length || seatsOf('company').length}
    <section data-swarm-section="companies">
      {@render divider(t('cplug.huddle.swarm.section.companies'), floor.companies.length)}
      <div class="pkp-grid" style:--cols={columnsOf('companies', density)} use:tierDrag={dragOf('companies')}>
        {#each floor.companies as it (it.key)}{@render item(it)}{/each}
        {@render slot('company')}
      </div>
      {@render pick('company')}
      {@render refused('company')}
    </section>
  {/if}

  {#if floor.projects.length || seatsOf('project').length}
    <section data-swarm-section="projects">
      {@render divider(t('cplug.huddle.swarm.section.projects'), floor.projects.length)}
      <div class="pkp-grid" style:--cols={columnsOf('projects', density)} use:tierDrag={dragOf('projects')}>
        {#each floor.projects as it (it.key)}{@render item(it)}{/each}
        {@render slot('project')}
      </div>
      {@render pick('project')}
      {@render refused('project')}
    </section>
  {/if}

  {#if floor.agents.length}
    <section data-swarm-section="agents">
      {@render divider(t('cplug.huddle.swarm.section.agents'), floor.agents.length)}
      <div class="pkp-grid" style:--cols={columnsOf('agents', density)} use:tierDrag={dragOf('agents')}>
        {#each floor.agents as it (it.key)}{@render item(it)}{/each}
      </div>
    </section>
  {/if}

  {#if showInactive || floor.inactive > 0}
    <div class="pkp-foot">
      <button type="button" class="pkp-toggle" data-swarm-toggle-inactive aria-pressed={showInactive} onclick={onToggleInactive}>
        {showInactive ? t('cplug.huddle.swarm.inactive.hide') : t('cplug.huddle.swarm.inactive.show', { n: floor.inactive })}
      </button>
    </div>
  {/if}
</div>

{#if menu?.item.agent}
  <NodeMenu agent={menu.item.agent} label={menu.item.label} anchor={menu.anchor} onClose={() => (menu = null)} />
{/if}

<style>
  @layer components {
    .pkp {
      --kl: var(--oc-ground-panel);
      padding: var(--oc-space-2);
      font-family: var(--font-mono);
      min-width: 0;
    }

    .pkp-alpha {
      display: flex;
      justify-content: center;
      padding: var(--oc-space-1) 0;
    }

    .pkp-div {
      display: flex;
      align-items: center;
      gap: 8px;
      margin: var(--oc-space-3) 0 var(--oc-space-1);
    }

    .pkp-div::after {
      order: 3;
      content: '';
      flex: 1;
      height: 1px;
      background: var(--oc-line-rule);
    }

    .pkp-label {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }

    .pkp-count {
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-micro);
      font-variant-numeric: tabular-nums;
    }

    .pkp-grid {
      display: grid;
      grid-template-columns: repeat(var(--cols), minmax(0, 1fr));
      gap: 16px 8px;
      justify-items: center;
      padding-block: 4px;
    }

    .pkp-it {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 8px;
      width: 100%;
      min-width: 0;
      padding: 0;
      border: 1px solid transparent;
      border-radius: 2px;
      background: none;
      color: var(--oc-text-secondary);
      font: inherit;
      cursor: pointer;
    }

    .pkp-it[aria-current='true'] {
      border-color: color-mix(in oklab, currentColor var(--oc-focus-keep, 75%), var(--oc-focus-lift, currentColor));
    }

    .pkp-it:hover .pkp-nm {
      color: var(--oc-text-bright);
    }

    .pkp-sq {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      flex: none;
      min-width: var(--pkp-s);
      min-height: var(--pkp-s);
    }

    .pkp-tx {
      display: flex;
      flex-direction: column;
      gap: 4px;
      min-width: 0;
      max-width: 100%;
      line-height: 1.3;
    }

    .pkp-l1 {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      min-width: 0;
    }

    .pkp-nm {
      min-width: 0;
      overflow: hidden;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
      font-weight: 500;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .pkp:not([data-flow]) [data-swarm-section='agents'] .pkp-nm {
      font-size: var(--oc-fs-micro);
    }

    .pkp-prov {
      display: inline-flex;
      flex: none;
      align-items: center;
      padding: 0 4px;
      border: 1px solid var(--oc-line-rule);
      border-radius: 2px;
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      line-height: 14px;
    }

    .pkp-wo {
      overflow: hidden;
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-micro);
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .pkp[data-flow] .pkp-grid {
      grid-template-columns: repeat(auto-fill, 7.5rem);
      justify-content: start;
    }

    .pkp[data-flow] .pkp-alpha {
      display: block;
    }

    .pkp[data-flow] .pkp-alpha .pkp-it {
      width: 7.5rem;
    }

    .pkp:not([data-density='detailed']) .pkp-tx {
      align-items: stretch;
      width: 100%;
    }

    .pkp:not([data-density='detailed']) .pkp-nm {
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 2;
      line-clamp: 2;
      overflow-wrap: break-word;
      text-align: center;
      text-overflow: ellipsis;
      white-space: normal;
    }

    .pkp:not([data-density='detailed']) .pkp-grid {
      align-items: start;
    }

    .pkp[data-density='detailed'] .pkp-grid {
      display: flex;
      flex-direction: column;
      gap: 0;
      justify-items: stretch;
    }

    .pkp[data-density='detailed'] .pkp-it {
      flex-direction: row;
      gap: 16px;
      padding: 8px 0;
      text-align: left;
      box-shadow: inset 0 -1px 0 var(--oc-line-faint);
    }

    .pkp[data-density='detailed'] .pkp-sq {
      min-width: calc(var(--pkp-s) + 18px);
    }

    .pkp[data-density='detailed'] .pkp-tx {
      flex: 1;
    }

    .pkp[data-density='detailed'] .pkp-l1 {
      justify-content: flex-start;
    }

    .pkp[data-density='detailed'] .pkp-nm {
      flex: 1;
    }

    .pkp[data-density='detailed'] .pkp-alpha {
      display: block;
    }

    .pkp-seat {
      width: var(--pkp-s);
      height: var(--pkp-s);
      color: var(--oc-text-dim);
      border: 1px dashed var(--oc-line-rule);
      border-radius: 2px;
    }

    .pkp-it--vacant {
      color: var(--oc-text-dim);
    }

    .pkp-it--vacant:hover .pkp-seat,
    .pkp-it--vacant[aria-busy='true'] .pkp-seat {
      border-color: var(--oc-text-muted);
    }

    .pkp-ask,
    .pkp-need {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      padding: var(--oc-space-1) 0;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
    }

    .pkp-ask-text,
    .pkp-need-text {
      flex: 1 1 12em;
      min-width: 0;
    }

    .pkp-ask-text[data-swarm-refusal] {
      flex-basis: 100%;
      color: var(--oc-coral);
    }

    .pkp-pick-list {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      max-height: 9rem;
      overflow-y: auto;
    }

    .pkp-foot {
      display: flex;
      justify-content: center;
      margin-top: var(--oc-space-3);
    }

    .pkp-toggle {
      padding: 0;
      border: 0;
      background: none;
      color: var(--oc-text-muted);
      font: inherit;
      font-size: var(--oc-fs-micro);
      cursor: pointer;
      text-decoration: underline;
      text-underline-offset: 2px;
    }

    .pkp-toggle:hover {
      color: var(--oc-text-bright);
    }
    .pkp-grid {
      --pkp-drag-ms: 180ms;
    }

    .pkp-grid > .pkp-it {
      touch-action: manipulation;
      -webkit-touch-callout: none;
    }

    .pkp-grid:global(.pkp-drag-on) {
      user-select: none;
      -webkit-user-select: none;
    }

    .pkp-grid:global(.pkp-drag-on) > .pkp-it {
      transition: transform var(--pkp-drag-ms) cubic-bezier(0.2, 0.8, 0.2, 1);
    }

    .pkp-grid:global(.pkp-drag-on) > .pkp-it:global(.pkp-drag-lift) {
      position: relative;
      z-index: 2;
      cursor: grabbing;
      transition: none;
      box-shadow: var(--oc-shadow-lift);
      opacity: 0.94;
    }

    .pkp-grid:global(.pkp-drag-on) > .pkp-it:global(.pkp-drag-lift.pkp-drag-home) {
      transition: transform var(--pkp-drag-ms) cubic-bezier(0.3, 1.3, 0.5, 1);
    }

    .pkp-grid > .pkp-it:global(.pkp-drag-plop) {
      animation: pkp-plop 320ms cubic-bezier(0.3, 1.5, 0.5, 1);
    }

    @keyframes pkp-plop {
      0% { transform: translateY(-4px) scale(1.06); }
      55% { transform: translateY(1px) scale(0.97, 1.03); }
      100% { transform: none; }
    }

    @media (prefers-reduced-motion: reduce) {
      .pkp-grid:global(.pkp-drag-on) > .pkp-it,
      .pkp-grid:global(.pkp-drag-on) > .pkp-it:global(.pkp-drag-lift.pkp-drag-home) {
        transition: none;
      }

      .pkp-grid > .pkp-it:global(.pkp-drag-plop) {
        animation: none;
      }
    }
  }
</style>
