
<script lang="ts">
    import type { TickView } from './rail-model.svelte';

    interface Props {
        tick: TickView;
        onjump: (ordinal: number) => void;
        onpeek: (tip: string, top: string) => void;
    }

    let { tick, onjump, onpeek }: Props = $props();

    const top = $derived(`${tick.y}px`);
</script>

<button data-base-exempt="a tick mark on the prompt rail, positioned by percent"
    type="button"
    class="prompt-tick"
    class:is-dim={tick.dim}
    class:is-current={tick.current}
    class:is-cluster={tick.cluster}
    data-ordinal={tick.ordinal}
    style:top
    title={tick.tip}
    data-tooltip-side="left"
    aria-label={tick.tip}
    onclick={() => onjump(tick.ordinal)}
    ontouchstart={() => onpeek(tick.tip, top)}
></button>

<style>
  @layer components {
      .prompt-tick {
          position: absolute;
          right: 0;
          width: 24px;
          height: 3px;
          padding: 0;
          border: none;
          background: none;
          cursor: pointer;
      }

      .prompt-tick::after {
          content: '';
          position: absolute;
          top: 0;
          right: 0;
          width: 12px;
          height: 100%;
          border-radius: 1px;
          background: var(--oc-text-muted);
          transition:
              width 0.1s ease,
              background 0.1s ease,
              opacity 0.1s ease;
      }

      .prompt-tick.is-dim {
          opacity: 0.3;
      }

      .prompt-tick.is-current::after {
          width: 16px;
          background: var(--oc-orange);
          opacity: 1;
      }

      .prompt-tick.is-cluster {
          height: 5px;
      }

      .prompt-tick:hover::after,
      .prompt-tick:focus-visible::after {
          width: 18px;
          background: var(--oc-orange-bright);
          outline: 1px solid var(--oc-orange);
          outline-offset: 1px;
      }

      .prompt-tick:hover,
      .prompt-tick:focus-visible {
          transform: none;
      }

      .prompt-tick:focus-visible {
          outline: none;
      }

      @media (max-width: 768px) {
          .prompt-tick {
              height: 4px;
          }

          .prompt-tick.is-cluster {
              height: 7px;
          }
  }
  }
</style>
