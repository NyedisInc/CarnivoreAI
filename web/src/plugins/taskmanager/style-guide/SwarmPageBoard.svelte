<script lang="ts">
  import { onMount } from 'svelte';
  import SwarmLedger from '../swarm/SwarmLedger.svelte';
  import SwarmPanel from '../swarm/SwarmPanel.svelte';
  import SwarmOrg from '../swarm/SwarmOrg.svelte';
  import SwarmSettingsForm from '../swarm/SwarmSettingsForm.svelte';
  import { readCharacterPack, DEFAULT_PACK, type CharacterPack } from '../swarm/characters/pack-reader';
  import { buildFloor } from '../swarm/floor';
  import { buildTree } from '../swarm/swarm-tree';
  import { AGENTS, COMPANIES, NOW, PROJECTS, SESSIONS, rowOf } from './swarm-fixture';

  const floor = buildFloor({ agents: AGENTS, sessions: SESSIONS, companies: COMPANIES, projects: PROJECTS, rowOf, showInactive: false });
  const tree = buildTree(floor);
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

<div class="sg-packpage">
  <div class="sg-packpage__part" data-part="ledger"><SwarmLedger {tree} agents={AGENTS} now={NOW} {pack} still onOpen={() => {}} /></div>
  <div class="sg-packpage__part" data-part="org"><SwarmOrg {tree} agents={AGENTS} now={NOW} {pack} still onOpen={() => {}} /></div>
  <div class="sg-packpage__part" data-part="squares">
    <SwarmPanel flow {floor} agents={AGENTS} density="expanded" now={NOW} {pack} still showInactive={false} onToggleInactive={() => {}} onOpen={() => {}} />
  </div>
  <div class="sg-packpage__part" data-part="settings"><SwarmSettingsForm /></div>
</div>

<style>
  @layer components {
    .sg-packpage {
      display: grid;
      gap: 24px;
      min-width: 0;
    }

    .sg-packpage__part {
      min-width: 0;
      overflow-x: auto;
    }
  }
</style>
