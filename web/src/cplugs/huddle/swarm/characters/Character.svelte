<script lang="ts">
  /*  hidden  */
  import { t } from '../../../sdk';
  import { packClock, watchVisibility } from './clock';
  import { bodyMorph, ensureDefs } from './dom';
  import type { AgentColor } from './family';
  import { contrastIndex, seriesIndex, seriesVar, ribbonsFor, stateLabelKey } from './look';
  import { DEFAULT_PACK, type CharacterPack } from './pack-reader';
  import { reducedMotion } from './reduced-motion.svelte';
  import { shapesFor, type ShapeKey } from './shapes';
  import { homeShapeOf, swarmLook } from './look-settings.svelte';
  import type { HomeShape } from './shapes';
  import { drawnState, heldShape, resolveState, STATES, sendState, type Tell } from './states';

  interface Props {
    state: string | null | undefined;
    size?: number;
    seed?: string | number;
    colorIndex?: number | null;
    color?: AgentColor | null;
    subs?: readonly (string | number)[];
    side?: 'l' | 'r';
    pack?: CharacterPack;
    still?: boolean;
    tell?: Tell | null;
    label?: string;
    rank?: string | null;
    shape?: HomeShape | null;
    background?: string | null;
  }
  let { state: rawState, size = 40, seed = '', colorIndex = null, color = null, subs = [], side = 'l', pack = DEFAULT_PACK, still, tell, label = '', rank = null, shape = null, background = null }: Props = $props();

  let el: HTMLElement | undefined = $state();
  const real = $derived(resolveState(rawState));
  const drawn = $derived(drawnState(real, swarmLook.animations));
  const st = $derived(drawn.state);
  const home = $derived(shape ?? homeShapeOf(rank));
  const def = $derived(STATES[st]);
  const isStill = $derived((still ?? reducedMotion()) || drawn.still);
  const shapes = $derived(shapesFor(pack.pixel));
  const ids = $derived.by(() => ensureDefs(shapes, pack.id, home));
  const bodyN = $derived(colorIndex ?? seriesIndex(seed));
  const ribbons = $derived(color ? ribbonsFor(st, bodyN, subs).map((r, i) => ({ ...r, color: color.ribbons[i] ?? color.contrast })) : ribbonsFor(st, bodyN, subs));
  const words = $derived(
    tell && sendState(tell) !== real
      ? t('cplug.huddle.swarm.character.tell', { state: t(stateLabelKey(real)), tell: t(stateLabelKey(sendState(tell))) })
      : t(stateLabelKey(real)),
  );
  const aria = $derived(label ? t('cplug.huddle.swarm.character.named', { name: label, state: words }) : words);
  const layers = $derived(`${st}|${isStill}|${pack.id}|${home}`);

  const memo: { held: ShapeKey | null } = { held: null };
  $effect(() => {
    void layers;
    memo.held = heldShape(st, home);
  });

  $effect(() => {
    if (!el) return;
    watchVisibility();
    return packClock.register(el, () => st, () => side);
  });
  $effect(() => {
    void st;
    if (el) packClock.reset(el);
  });
  $effect(() => {
    if (!el || !isStill) return;
    const g = st === 'talking' ? ([side === 'r' ? -0.95 : 0.95, 0] as const) : (def.stillGaze ?? [0, 0]);
    el.style.setProperty('--gx', String(g[0]));
    el.style.setProperty('--gy', String(g[1]));
  });
</script>

<div
  bind:this={el}
  class="pk-sq"
  data-state={st}
  data-status={real}
  data-shape={home}
  data-tile={background ? '' : undefined}
  style:--tile={background}
  data-seed={String(seed)}
  data-pack={pack.id}
  data-still={isStill ? '' : undefined}
  role="img"
  aria-label={aria}
  style:--s="{size}px"
  style:--c={color ? color.body : seriesVar(bodyN)}
  style:--side={side === 'r' ? -1 : 1}
  style:--td={side === 'r' ? '-1.2s' : '0s'}
  style:--gc={color ? color.contrast : seriesVar(contrastIndex(bodyN))}
>
  {#key layers}
    <div class="pk-fx pk-fxb" aria-hidden="true">
      {#each ribbons as r, i (i)}
        <div class="pk-orb" style="--i:{i};--k:{r.color};--t:{r.slot.t}deg;--rx:{r.slot.rx}deg;--d:{r.slot.d}s;--dir:{r.slot.dir};--a0:{r.slot.a0}deg;--r:{((r.slot.R * 140) / 60).toFixed(3)}">
          <div class="pk-spin"><svg viewBox="-70 -70 140 140"><use href="#{ids.rib}" /></svg></div>
        </div>
      {/each}
    </div>
    <div class="pk-tl" aria-hidden="true">
      <div class="pk-mv">
        <div class="pk-sz">
          {#if def.glow}<div class="pk-gw" aria-hidden="true"></div>{/if}
          {#if def.cor}<div class="pk-cr"><svg class="pk-cor" viewBox="0 0 100 100"><use href="#{ids.cor[def.cor]}" /></svg></div>{/if}
          <svg class="pk-bd" viewBox="0 0 100 100"><path class="pk-shp" use:bodyMorph={{ state: st, held: memo.held, shapes, still: isStill, home }} />{#if st === 'dead'}<path class="pk-rip" d={shapes.stone.rip} /><path class="pk-gl" d={shapes.stone.ground} />{/if}</svg>
          <div class="pk-ey"><div class="pk-ex"><i class="pk-e"></i><i class="pk-e"></i></div></div>
        </div>
      </div>
    </div>
    <div class="pk-fx pk-fxf" aria-hidden="true">
      {#each ribbons as r, i (i)}
        <div class="pk-orb" style="--i:{i};--k:{r.color};--t:{r.slot.t}deg;--rx:{r.slot.rx}deg;--d:{r.slot.d}s;--dir:{r.slot.dir};--a0:{r.slot.a0}deg;--r:{((r.slot.R * 140) / 60).toFixed(3)}">
          <div class="pk-spin"><svg viewBox="-70 -70 140 140"><use href="#{ids.rib}" /></svg></div>
        </div>
      {/each}
      {#if def.dots}
        <i class="pk-dt" style="--x:-.3em;--o:.45;--dl:0s"></i><i class="pk-dt pk-dm" style="--x:0em;--o:1;--dl:.08s"></i><i class="pk-dt" style="--x:.3em;--o:.45;--dl:.16s"></i>
      {/if}
      {#if def.comet}
        <div class="pk-cm"><svg viewBox="-12 -12 24 60"><use href="#{ids.cmt}" /></svg></div>
      {/if}
      {#if def.talk}<i class="pk-tk"></i>{/if}
    </div>
  {/key}
</div>
