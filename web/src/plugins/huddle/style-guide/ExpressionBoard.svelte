<script lang="ts">
  import { onMount } from 'svelte';
  import Character from '../swarm/characters/Character.svelte';
  import { packClock } from '../swarm/characters/clock';
  import { applyExpression, EXPRESSIONS, type Expression } from '../swarm/characters/expressions';
  import { readCharacterPack, PIXEL_PACK, DEFAULT_PACK, type CharacterPack } from '../swarm/characters/pack-reader';

  let stage: HTMLElement | undefined = $state();
  let sheet: HTMLElement | undefined = $state();
  let themePack: CharacterPack = $state(DEFAULT_PACK);
  let current = $state(EXPRESSIONS[0]!.name);
  let cycling = $state(false);

  function activePack(): CharacterPack {
    const themes = (window as unknown as { Themes?: { getActiveGlobal?: () => { characters?: unknown } | null } }).Themes;
    return readCharacterPack(themes?.getActiveGlobal?.()?.characters ?? null);
  }

  function play(x: Expression): void {
    current = x.name;
    for (const sq of stage?.querySelectorAll<HTMLElement>('.pk-sq') ?? []) packClock.play(sq, x);
  }

  onMount(() => {
    themePack = activePack();
    const follow = (): void => {
      themePack = activePack();
    };
    document.addEventListener('style-guide:theme', follow);
    return () => document.removeEventListener('style-guide:theme', follow);
  });

  $effect(() => {
    if (!cycling) return;
    let i = EXPRESSIONS.findIndex((x) => x.name === current);
    const id = window.setInterval(() => {
      i = (i + 1) % EXPRESSIONS.length;
      play(EXPRESSIONS[i]!);
    }, 1500);
    return () => window.clearInterval(id);
  });

  $effect(() => {
    const pixel = themePack.pixel;
    for (const cell of sheet?.querySelectorAll<HTMLElement>('[data-ex]') ?? []) {
      const x = EXPRESSIONS.find((e) => e.name === cell.dataset.ex);
      if (x) for (const sq of cell.querySelectorAll<HTMLElement>('.pk-sq')) applyExpression(sq, x, pixel);
    }
  });
</script>

<div class="sg-ex">
  <div class="sg-ex-stage" bind:this={stage}>
    {#each [28, 40, 64] as size (size)}
      <Character state="idle" {size} seed="face" pack={themePack} />
    {/each}
    <Character state="idle" size={64} seed="face" pack={PIXEL_PACK} />
    <div class="sg-ex-now"><b>{current}</b><button type="button" class="sg-ex-btn" aria-pressed={cycling} onclick={() => (cycling = !cycling)}>cycle all</button></div>
  </div>
  <div class="sg-ex-picker" role="group" aria-label="expressions">
    {#each EXPRESSIONS as x (x.name)}
      <button type="button" class="sg-ex-btn" aria-pressed={current === x.name} onclick={() => play(x)}>{x.name}</button>
    {/each}
  </div>
  <div class="sg-ex-sheet" bind:this={sheet}>
    {#each EXPRESSIONS as x (x.name)}
      <div class="sg-ex-cell" data-ex={x.name}>
        <div class="sg-ex-faces">
          <Character state="idle" size={28} seed="face" pack={themePack} still={true} />
          <Character state="idle" size={64} seed="face" pack={themePack} still={true} />
        </div>
        <span>{x.name}</span>
      </div>
    {/each}
  </div>
</div>
