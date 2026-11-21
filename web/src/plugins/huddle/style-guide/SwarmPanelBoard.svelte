<script lang="ts">
  import { onMount } from 'svelte';
  import SwarmPanel from '../swarm/SwarmPanel.svelte';
  import { readCharacterPack, DEFAULT_PACK, type CharacterPack } from '../swarm/characters/pack-reader';
  import { buildFloor } from '../swarm/floor';
  import type { PanelDensity } from '../swarm/panel-state';
  import { AGENTS, COMPANIES, NOW, PROJECTS, ROWS, SESSIONS, rowOf } from './swarm-fixture';

  const COLUMNS: ReadonlyArray<{ density: PanelDensity; shown: boolean }> = [
    { density: 'condensed', shown: false }, { density: 'expanded', shown: false }, { density: 'detailed', shown: false }, { density: 'expanded', shown: true },
  ];
  let shown = $state(COLUMNS.map((c) => c.shown));
  const floors = $derived(shown.map((on) => buildFloor({ agents: AGENTS, sessions: SESSIONS, companies: COMPANIES, projects: PROJECTS, rowOf, showInactive: on })));

  let pack: CharacterPack = $state(DEFAULT_PACK);

  function activePack(): CharacterPack {
    const themes = (window as unknown as { Themes?: { getActiveGlobal?: () => { characters?: unknown } | null } }).Themes;
    return readCharacterPack(themes?.getActiveGlobal?.()?.characters ?? null);
  }

  onMount(() => {
    pack = activePack();
    const follow = (): void => {
      pack = activePack();
    };
    document.addEventListener('style-guide:theme', follow);
    return () => document.removeEventListener('style-guide:theme', follow);
  });
</script>

<div class="sg-packpanel">
  {#each COLUMNS as col, i (i)}
    <div class="sg-packpanel__col" data-density-col={col.density} data-inactive-col={shown[i] ? 'shown' : 'hidden'}>
      <span class="sg-packpanel__cap">{col.density}{col.shown ? ', inactive shown' : ''}</span>
      <div class="sg-packpanel__frame">
        <SwarmPanel floor={floors[i]!} agents={AGENTS} density={col.density} now={NOW} {pack} showInactive={shown[i]!}
                   onToggleInactive={() => (shown[i] = !shown[i])} onOpen={() => {}} onTurnOn={() => {}} />
      </div>
    </div>
  {/each}
</div>

<style>
  @layer components {
    .sg-packpanel {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
      align-items: start;
    }

    .sg-packpanel__col {
      display: flex;
      flex-direction: column;
      gap: 8px;
      min-width: 0;
    }

    .sg-packpanel__cap {
      color: var(--oc-text-muted);
      font-size: var(--oc-fs-micro);
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }

    .sg-packpanel__frame {
      max-width: 360px;
      border: 1px solid var(--oc-line-rule);
      background: var(--oc-ground-panel);
    }
  }
</style>
