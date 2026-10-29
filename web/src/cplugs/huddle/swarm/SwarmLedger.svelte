<script lang="ts">
  import { providerMark, t, workingOnText } from '../../sdk';
  import { colorBook, type ColorBook } from './agent-colors.svelte';
  import { Character, type CharacterPack, DEFAULT_PACK } from './characters';
  import type { FloorTarget } from './floor';
  import { ledgerRows, type SwarmTree } from './swarm-tree';
  import { alertOf, seedOf, subSeeds, talkingSide, type PanelAgent } from './panel-state';
  import { backgroundFor, colorFor, markRankOf, shapeFor, stateFor, sendFor } from './node-look';
  import { MachineBadge, TaskMark } from '../../sdk/ui';

  interface Props {
    tree: SwarmTree;
    agents: readonly PanelAgent[];
    now: number;
    pack?: CharacterPack;
    colors?: ColorBook;
    still?: boolean;
    busy?: string | null;
    onOpen: (target: FloorTarget, terminal?: boolean) => void;
  }
  const { tree, agents, now, pack = DEFAULT_PACK, colors, still, busy = null, onOpen }: Props = $props();
  const book = $derived(colors ?? colorBook(agents, null));

  let collapsed = $state<ReadonlySet<string>>(new Set());
  const rows = $derived(ledgerRows(tree, collapsed));

  function fold(key: string): void {
    const next = new Set(collapsed);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    collapsed = next;
  }
</script>

<div class="pkg-ledger" data-swarm-ledger>
  <div class="pkg-head pkg-cols" aria-hidden="true">
    <span>{t('cplug.huddle.swarm.ledger.col.name')}</span>
    <span>{t('cplug.huddle.swarm.ledger.col.kind')}</span>
    <span>{t('cplug.huddle.swarm.ledger.col.status')}</span>
    <span>{t('cplug.huddle.swarm.ledger.col.job')}</span>
    <span>{t('cplug.huddle.swarm.ledger.col.effort')}</span>
    <span>{t('cplug.huddle.swarm.ledger.col.alert')}</span>
  </div>
  <div role="list">
  {#each rows as node (node.item.key)}
    {@const it = node.item}
    {@const agent = it.agent}
    {@const state = stateFor(it, now)}
    {@const rung = agent ? alertOf(agent) : null}
    {@const mark = agent ? providerMark(agent.harness ?? null, 12) : null}
    <div class="pkg-row" role="listitem" data-swarm-row={it.key} data-swarm-depth={node.depth} data-swarm-rank={it.ordinary ? 'session' : it.rank}
         data-swarm-state={state} data-swarm-active={it.active} style:--pkg-depth={node.depth}>
      {#if node.children.length}
        <button type="button" class="pkg-caret" data-swarm-fold={it.key} aria-expanded={!collapsed.has(it.key)}
                aria-label={t(collapsed.has(it.key) ? 'cplug.huddle.swarm.ledger.expand' : 'cplug.huddle.swarm.ledger.collapse', { name: it.label })}
                onclick={() => fold(it.key)}>{collapsed.has(it.key) ? '+' : '-'}</button>
      {:else}
        <span class="pkg-caret pkg-caret--none" aria-hidden="true"></span>
      {/if}
      <button type="button" class="pkg-main pkg-cols" aria-busy={it.vacant && busy === it.key ? 'true' : undefined}
              data-agent-drawer-opener={it.vacant ? undefined : ''}
              title={it.vacant ? t('cplug.huddle.swarm.seat.title', { name: it.label }) : undefined}
              onclick={(e) => onOpen(it.target, e.shiftKey)}>
        <span class="pkg-who">
        <span class="pkg-face">
          {#if agent}
            <Character {state} size={28} seed={seedOf(agent)} color={colorFor(book, it)} subs={it.ordinary ? [] : subSeeds(agent, agents)}
                       side={talkingSide(agent, agents, now)} tell={sendFor(it)} {pack} {still} rank={agent.rank} shape={shapeFor(it)} background={backgroundFor(it)} label={it.label} />
          {:else}
            <span class="pkg-seat" data-swarm-roll={it.rollup}></span>
          {/if}
        </span>
        <span class="pkg-name">
          <b class="pkg-nm"><TaskMark rank={markRankOf(it)} />{it.label}</b>
          <MachineBadge hostKey={agent?.host_key ?? it.row?.host_key} label={agent?.host_label ?? it.row?.host_label} state={it.row?.host_state} />
          {#if mark}<span class="pkg-prov" title={mark.label}>{#if mark.svg}{@html mark.svg}{:else}{mark.label}{/if}</span>{/if}
        </span>
        </span>
        <span class="pkg-rank">{t(`cplug.huddle.swarm.rank.${it.ordinary ? 'session' : it.rank}`)}</span>
        <span class="pkg-state">{it.vacant ? t('cplug.huddle.swarm.seat.vacant') : t(`cplug.huddle.swarm.state.${state}`)}</span>
        <span class="pkg-job">{agent?.job || (it.row ? workingOnText(it.row) : '')}</span>
        <span class="pkg-effort">{agent?.effort ?? ''}</span>
        <span class="pkg-alert" data-swarm-alert={rung ?? undefined}>{rung ? t(`cplug.huddle.swarm.state.alert_${rung}`) : ''}</span>
      </button>
    </div>
  {/each}
  </div>
</div>

<style>
  @layer components {
    .pkg-ledger {
      font-family: var(--font-mono);
      min-width: 0;
    }

    .pkg-cols {
      display: grid;
      grid-template-columns: minmax(14em, 2fr) 6.5em minmax(8em, 1fr) minmax(0, 2.4fr) 5em 10em;
      align-items: center;
      gap: 12px;
    }

    .pkg-head {
      padding: 4px 4px 4px 28px;
      border: 1px solid transparent;
      box-shadow: inset 0 -1px 0 var(--oc-line-rule);
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-label);
    }

    .pkg-head > span {
      overflow: hidden;
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.16em;
      text-transform: uppercase;
      white-space: nowrap;
    }

    .pkg-row {
      position: relative;
      box-shadow: inset 0 -1px 0 var(--oc-line-faint);
    }

    .pkg-caret {
      position: absolute;
      top: 50%;
      left: calc(var(--pkg-depth) * 20px);
      width: 20px;
      padding: 0;
      border: 1px solid transparent;
      border-radius: 2px;
      background: none;
      color: var(--oc-text-muted);
      font: inherit;
      font-size: var(--oc-fs-label);
      transform: translateY(-50%);
      cursor: pointer;
    }

    .pkg-caret--none {
      cursor: default;
    }

    .pkg-caret:hover {
      color: var(--oc-text-bright);
    }

    .pkg-main {
      width: 100%;
      min-width: 0;
      padding: 6px 4px 6px 28px;
      border: 1px solid transparent;
      border-radius: 2px;
      background: none;
      color: var(--oc-text-secondary);
      font: inherit;
      font-size: var(--oc-fs-label);
      text-align: left;
      cursor: pointer;
    }

    .pkg-main:hover .pkg-nm {
      color: var(--oc-text-bright);
    }

    .pkg-who {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
      padding-left: calc(var(--pkg-depth) * 20px);
    }

    .pkg-face {
      display: inline-flex;
      flex: none;
      align-items: center;
      justify-content: center;
      width: 28px;
      height: 28px;
    }

    .pkg-seat {
      width: 28px;
      height: 28px;
      border: 1px dashed var(--oc-line-rule);
      border-radius: 2px;
    }

    .pkg-name {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }

    .pkg-nm {
      min-width: 0;
      overflow: hidden;
      color: var(--oc-text-secondary);
      font-weight: 500;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .pkg-prov {
      display: inline-flex;
      flex: none;
      align-items: center;
      padding: 0 4px;
      border: 1px solid var(--oc-line-rule);
      border-radius: 2px;
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-micro);
      line-height: 14px;
    }

    .pkg-rank {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }

    .pkg-state,
    .pkg-job,
    .pkg-effort {
      min-width: 0;
      overflow: hidden;
      color: var(--oc-text-dim);
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .pkg-alert {
      overflow: hidden;
      white-space: nowrap;
      color: var(--oc-yellow);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }

    .pkg-alert[data-swarm-alert='immediate'],
    .pkg-alert[data-swarm-alert='flash'] {
      color: var(--oc-coral);
    }

    @media (max-width: 767px) {
      .pkg-cols {
        grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      }

      .pkg-head > :nth-child(2),
      .pkg-head > :nth-child(n + 4),
      .pkg-rank,
      .pkg-job,
      .pkg-effort,
      .pkg-alert {
        display: none;
      }
    }
  }
</style>
