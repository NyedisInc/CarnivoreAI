<script lang="ts">
  import { onMount } from 'svelte';
  import Character from '../swarm/characters/Character.svelte';
  import { seriesIndex } from '../swarm/characters/look';
  import { readCharacterPack, PIXEL_PACK, DEFAULT_PACK, type CharacterPack } from '../swarm/characters/pack-reader';
  import { reducedMotion } from '../swarm/characters/reduced-motion.svelte';
  import { ALL_STATES, STATES, type CharacterState } from '../swarm/characters/states';

  let { part = 'theme' }: { part?: 'theme' | 'pixel' } = $props();

  const REPLAY: Partial<Record<CharacterState, number>> = {
    working: 9,
    working_subagent: 9,
    question: 12,
    notice: 6,
    finished_unread: 6,
    dead: 8,
    asleep: 8,
    question_waiting: 9,
    done: 6,
    escalating: 6,
    learning: 6,
    promoted: 6,
    alert_routine: 6,
  };

  let themePack: CharacterPack = $state(DEFAULT_PACK);
  let plays: Partial<Record<CharacterState, number>> = $state({});
  const pack = $derived(part === 'pixel' ? PIXEL_PACK : themePack);
  const sizes = $derived(part === 'pixel' ? [40] : [28, 40, 64]);

  function activePack(): CharacterPack {
    const themes = (window as unknown as { Themes?: { getActiveGlobal?: () => { characters?: unknown } | null } }).Themes;
    return readCharacterPack(themes?.getActiveGlobal?.()?.characters ?? null);
  }

  function seedFor(index: number): number {
    for (let k = 0; k < 8; k++) if (seriesIndex(k) === index) return k;
    return 0;
  }

  function subsFor(seed: string): number[] {
    return [2, 4, 6].map((shift) => seedFor(seriesIndex(seed, shift)));
  }

  onMount(() => {
    themePack = activePack();
    const follow = (): void => {
      themePack = activePack();
    };
    document.addEventListener('style-guide:theme', follow);
    const timers: number[] = [];
    if (!reducedMotion()) {
      for (const st of ALL_STATES) {
        const period = REPLAY[st];
        if (!period) continue;
        const replay = (): void => {
          if (!document.hidden) plays[st] = (plays[st] ?? 0) + 1;
        };
        timers.push(
          window.setTimeout(
            () => {
              replay();
              timers.push(window.setInterval(replay, period * 1000));
            },
            period * 1000 * (0.4 + 0.6 * Math.random()),
          ),
        );
      }
    }
    return () => {
      document.removeEventListener('style-guide:theme', follow);
      for (const id of timers) {
        window.clearTimeout(id);
        window.clearInterval(id);
      }
    };
  });
</script>

<div class="sg-pack-wrap">
  <div class="sg-pack-board">
    {#each ALL_STATES as st (st)}
      <div class="sg-pack-row" data-row={st}>
        <div class="sg-pack-name"><b>{st}</b><span>{STATES[st].kind}</span></div>
        {#key plays[st] ?? 0}
          {#each sizes as size (size)}
            <div class="sg-pack-cell">
              {#if st === 'talking'}
                <Character state={st} {size} seed="Tully" side="l" {pack} />
                <Character state={st} {size} seed="Pike" side="r" {pack} />
              {:else}
                <Character state={st} {size} seed={'m' + st} subs={st === 'working_subagent' ? subsFor('m' + st) : []} {pack} />
              {/if}
            </div>
          {/each}
        {/key}
        {#if part === 'theme'}
          <div class="sg-pack-cell">
            {#if st === 'talking'}
              <Character state={st} size={40} seed="Tully" side="l" {pack} still={true} />
              <Character state={st} size={40} seed="Pike" side="r" {pack} still={true} />
            {:else}
              <Character state={st} size={40} seed={'m' + st} subs={st === 'working_subagent' ? subsFor('m' + st) : []} {pack} still={true} />
            {/if}
          </div>
        {/if}
      </div>
    {/each}
  </div>
</div>
