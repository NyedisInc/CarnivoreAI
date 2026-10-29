<script lang="ts">
  /* the glance area */
  import { t } from '../i18n/index.svelte';
  import GlanceTiles from './GlanceTiles.svelte';
  import GlanceOptionsOverlay from './GlanceOptionsOverlay.svelte';
  import GlanceMenu from './GlanceMenu.svelte';
  import { createGlanceZone, type GlanceEntry as Entry } from './area-zones';

  let { entries, onopen, options = false }: { entries: Entry[]; onopen: () => void; options?: boolean } = $props();

  let menu = $state<Entry | null>(null);
  let optionsFor = $state<string | null>(null);
  let anchor = $state<HTMLElement | null>(null);

  const zone = createGlanceZone(
    () => entries,
    (entry, at) => {
      const el = at instanceof HTMLElement ? at : (at.anchor ?? null);
      anchor = el?.closest<HTMLElement>('[data-glance-row-place]') ?? el;
      menu = entry;
    },
  );

  function showMenu(entry: Entry, at: HTMLElement): void {
    zone.openMenu(entry.key, at);
  }

  function onWrapMenu(entry: Entry, event: MouseEvent): void {
    if (event.defaultPrevented) return;
    event.preventDefault();
    showMenu(entry, event.currentTarget as HTMLElement);
  }
</script>

<div class="dz-glances" role="group" aria-label={t('drawer_zone.glance')} data-zone-glances data-fit-scroll-x>
  {#each entries as entry (entry.key)}
    {#if options}
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <span class="dz-gwrap" data-glance-row-place={entry.key} oncontextmenu={(event) => onWrapMenu(entry, event)}>
        <GlanceTiles placement={entry.key} widget={entry.widget} manifest={entry.manifest} options={entry.options} {onopen} onmenu={(at) => showMenu(entry, at)} />
      </span>
    {:else}
      <GlanceTiles placement={entry.key} widget={entry.widget} manifest={entry.manifest} options={entry.options} {onopen} />
    {/if}
  {/each}
</div>
{#if menu}
  {@const shown = menu}
  <GlanceMenu placement={shown.key} widget={shown.widget} options={shown.options ?? {}} {anchor} onClose={() => (menu = null)} onSettings={(key) => (optionsFor = key)} />
{/if}
{#if optionsFor}
  <GlanceOptionsOverlay placement={optionsFor} {anchor} onClose={() => (optionsFor = null)} />
{/if}

<style>
  @layer components {
    /* padding */
    .dz-glances {
      display: flex;
      align-items: center;
      gap: var(--oc-space-1);
      padding: calc(var(--oc-space-1) / 2) var(--oc-space-2);
      box-sizing: border-box;
      overflow-x: auto;
    }

    .dz-gwrap {
      display: inline-flex;
      gap: var(--oc-space-1);
    }
  }
</style>
