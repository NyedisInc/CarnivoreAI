<script lang="ts">
  import type { CompassView } from '../dock-compass';

  let { view }: { view: CompassView | null } = $props();
</script>

{#if view}
  <div
    class="dock-compass"
    aria-hidden="true"
    data-compass={view.window}
    style:left="{view.plate.x}px"
    style:top="{view.plate.y}px"
    style:width="{view.plate.w}px"
    style:height="{view.plate.h}px"
  >
    {#each view.icons as icon (icon.dir)}
      <span
        class="dock-compass__icon"
        class:dock-compass__icon--hot={icon.hot}
        class:dock-compass__icon--off={!icon.enabled}
        data-dir={icon.dir}
        style:left="{icon.rect.x - view.plate.x}px"
        style:top="{icon.rect.y - view.plate.y}px"
        style:width="{icon.rect.w}px"
        style:height="{icon.rect.h}px"
      >
        <svg viewBox="0 0 16 16" focusable="false">
          <rect class="dock-compass__frame" x="1.5" y="1.5" width="13" height="13" />
          {#if icon.dir === 'up'}
            <rect class="dock-compass__fill" x="1.5" y="1.5" width="13" height="6" />
          {:else if icon.dir === 'down'}
            <rect class="dock-compass__fill" x="1.5" y="8.5" width="13" height="6" />
          {:else if icon.dir === 'left'}
            <rect class="dock-compass__fill" x="1.5" y="1.5" width="6" height="13" />
          {:else if icon.dir === 'right'}
            <rect class="dock-compass__fill" x="8.5" y="1.5" width="6" height="13" />
          {:else}
            <rect class="dock-compass__fill" x="1.5" y="1.5" width="7" height="4" />
          {/if}
        </svg>
      </span>
    {/each}
  </div>
{/if}
