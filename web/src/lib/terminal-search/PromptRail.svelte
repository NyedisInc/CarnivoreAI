<!--
  The prompt rail: a thin strip of ticks down the terminal's right edge,
  one per prompt the user typed.

  THE DOM HALF ONLY. Every rule about what a tick points at, when the
  strip rescans and what "current" means lives in ./rail-model.svelte.ts,
  which is also where the marker arithmetic is written down.

  HIDING IS `hidden`, NOT A DISPLAY OVERRIDE, and the guard rule below is
  not belt and braces. `[hidden] { display: none }` lives in the
  USER-AGENT stylesheet, where ANY author `display` declaration outranks
  it. This project has already paid for that once: measured an earlier date, a
  `hidden` archive panel whose class carried `display: flex` rendered
  anyway and squeezed the list beside it. The rule declares no `display`
  today, so the guard is what stops one being added later and painting an
  empty strip over the terminal in every session that has no prompts and
  on every alternate-screen app.

  THE TOOLTIP IS RENDERED AS WELL AS SET AS `title`. A `title` covers a
  mouse (it is the app's one delayed tooltip, web/src/lib/tooltip/
  tooltip.ts); a thumb never hovers, so on a TAP the strip also paints this
  box and the tick hands it a measured `top`. It wears the same look as
  that one tooltip by carrying the same `popup-focus` class (issue #981).
-->
<script lang="ts">
    import PromptTick from './PromptTick.svelte';
    import { t } from '../i18n/index.svelte';
    import type { RailModel } from './rail-model.svelte';

    interface Props {
        rail: RailModel;
    }

    let { rail }: Props = $props();

    let el = $state<HTMLDivElement | null>(null);
    let tipText = $state('');
    let tipTop = $state('');
    let tipShown = $state(false);

    $effect(() => {
        rail.setElement(el);
        // nothing at all
        if (!el) return () => rail.setElement(null);
        const node = el;
        node.addEventListener('click', jumpNear);
        return () => {
            node.removeEventListener('click', jumpNear);
            rail.setElement(null);
        };
    });

    function peek(tip: string, top: string): void {
        if (!tip) return;
        tipText = tip;
        tipTop = top;
        tipShown = true;
    }

    /* <button> */
    function jumpNear(event: MouseEvent): void {
        if (!el || event.target !== el) return;
        const ordinal = rail.ordinalNear(event.clientY - el.getBoundingClientRect().top);
        if (ordinal) rail.jumpTo(ordinal);
    }
</script>

<!-- <button> -->
<div
    bind:this={el}
    class="terminal-prompt-rail"
    aria-label={t('terminal.prompts.label')}
    hidden={rail.hidden}
    onmouseleave={() => {
        tipShown = false;
    }}
    role="presentation"
>
    <div class="prompt-rail-tooltip" role="tooltip" hidden={!tipShown} style:top={tipTop}>
        {tipText}
    </div>
    {#each rail.tickViews as tick (tick.ordinal)}
        <PromptTick {tick} onjump={(ordinal) => rail.jumpTo(ordinal)} onpeek={peek} />
    {/each}
</div>

<style>
  @layer components {
      .terminal-prompt-rail {
          position: absolute;
          top: 0;
          right: 0;
          bottom: 0;
          width: 24px;
          pointer-events: auto;
          cursor: pointer;
      }

      .terminal-prompt-rail[hidden] {
          display: none !important;
      }

      .prompt-rail-tooltip {
          position: absolute;
          right: 28px;
          z-index: 32;
          max-width: min(280px, 60vw);
      }

      .prompt-rail-tooltip[hidden] {
          display: none;
      }
  }
</style>
