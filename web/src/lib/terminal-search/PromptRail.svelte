
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

    function jumpNear(event: MouseEvent): void {
        if (!el || event.target !== el) return;
        const ordinal = rail.ordinalNear(event.clientY - el.getBoundingClientRect().top);
        if (ordinal) rail.jumpTo(ordinal);
    }
</script>


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
