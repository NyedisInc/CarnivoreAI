<script lang="ts">
  import { icons, type SizedIcon } from '../../opscenter/ui/icons';

  let { size = 18 }: { size?: number } = $props();

  const BOT_BOX = 11;
  const BOT_AT = (24 - BOT_BOX) / 2;
  const BOT_VIEWBOX = '1.5 0.5 17 16.5';

  const ring = icons['cycle'] as string;
  const bot = (icons['bot'] as SizedIcon).path;
</script>

<svg
  class="bcm"
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="1.5"
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
  focusable="false"
  data-icon="bot-cycle"
>
  <g class="bcm-ring">{@html ring}</g>
  <svg class="bcm-bot" x={BOT_AT} y={BOT_AT} width={BOT_BOX} height={BOT_BOX} viewBox={BOT_VIEWBOX}>{@html bot}</svg>
</svg>

<style>
  @layer components {
    .bcm {
      display: block;
      flex: none;
    }

    .bcm-ring {
      opacity: 0.7;
    }

    .bcm-bot :global([stroke-width]) {
      stroke-width: 1.9;
    }
  }
</style>
