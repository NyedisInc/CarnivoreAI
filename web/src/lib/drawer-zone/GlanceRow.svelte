<script lang="ts">
  import { flushSync, onDestroy } from 'svelte';
  import { t } from '../i18n/index.svelte';
  import { manifestById } from '../../opscenter/widgets/core-manifests';
  import { registerDropHost } from '../motion-grid';
  import { mountStack, type Stack } from '../zone-motion/stack-motion';
  import { drawerZone } from './zone-store.svelte';
  import { isRepeatable } from './zone-model';
  import { MAX_GLANCE_PLACEMENTS } from './glance-model';
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

  const ZONE_ID = 'zone:drawer-glance';
  const PENDING_PX = 72;

  let pending = $state<{ id: string; kind: string } | null>(null);
  const cells = $derived([
    ...entries.map((entry) => ({ id: entry.key, entry, kind: null as string | null })),
    ...(pending ? [{ id: pending.id, entry: null, kind: pending.kind }] : []),
  ]);
  const order = $derived(cells.map((cell) => cell.id));

  let root = $state<HTMLElement | null>(null);
  let stack: Stack | null = null;
  let stackEl: HTMLElement | null = null;

  function ensure(node: HTMLElement): Stack {
    const row = node.parentElement as HTMLElement;
    if (stack && stackEl === row) return stack;
    stack?.destroy();
    stackEl = row;
    stack = mountStack(row, {
      axis: 'x',
      order: () => order,
      gap: 4,
      pad: { x: 8, y: 2 },
      grabControls: true,
      place: (id, index, external) => {
        if (external && pending) {
          const kind = pending.kind;
          pending = null;
          drawerZone.addGlance(kind, isRepeatable(kind), index);
        } else if (!external) drawerZone.moveGlance(id, index);
      },
      label: (id) => {
        const kind = cells.find((one) => one.id === id)?.entry?.widget;
        const manifest = kind ? manifestById(kind) : undefined;
        return manifest ? t(manifest.titleKey) : id;
      },
    });
    stack.handle.on('settle', () => {
      if (pending) pending = null;
    });
    return stack;
  }

  function cell(node: HTMLElement, id: string): { update(id: string): void; destroy(): void } {
    return ensure(node).cell(node, id);
  }

  $effect(() => {
    void order;
    stack?.sync();
  });

  const takes = (kind: string): boolean =>
    !!manifestById(kind) && drawerZone.glance.length < MAX_GLANCE_PLACEMENTS && (isRepeatable(kind) || !drawerZone.glance.some((p) => p.widget === kind));

  $effect(() => {
    if (!options || !root) return;
    return registerDropHost(root, {
      id: ZONE_ID,
      takes,
      accept(kind, ev) {
        if (!takes(kind)) return false;
        pending = { id: `pending:${kind}`, kind };
        flushSync();
        const ok = !!stack?.handle.beginExternal({ id: `pending:${kind}`, rect: { x: 0, y: 0, w: PENDING_PX, h: stackEl?.clientHeight || 28 }, grab: { x: PENDING_PX / 2, y: 14 } }, ev);
        if (!ok) pending = null;
        return ok;
      },
      add: (kind) => takes(kind) && drawerZone.addGlance(kind, isRepeatable(kind)) !== null,
    });
  });

  onDestroy(() => {
    stack?.destroy();
    stack = null;
  });

  function onWrapMenu(entry: Entry, event: MouseEvent): void {
    if (event.defaultPrevented) return;
    event.preventDefault();
    showMenu(entry, event.currentTarget as HTMLElement);
  }
</script>

<div class="dz-glances" class:dz-glances--motion={options} bind:this={root} role="group" aria-label={t('drawer_zone.glance')} data-zone-glances data-fit-scroll-x>
  {#each options ? cells : entries.map((entry) => ({ id: entry.key, entry, kind: null })) as one (one.id)}
    {#if options}
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <div class="dz-gcell" use:cell={one.id}>
        {#if one.entry}
          {@const entry = one.entry}
          <span class="dz-gwrap" data-glance-row-place={entry.key} oncontextmenu={(event) => onWrapMenu(entry, event)}>
            <GlanceTiles placement={entry.key} widget={entry.widget} manifest={entry.manifest} options={entry.options} {onopen} onmenu={(at) => showMenu(entry, at)} />
          </span>
        {:else}
          <span class="dz-gpending" data-zone-pending>{one.kind && manifestById(one.kind) ? t(manifestById(one.kind)!.titleKey) : ''}</span>
        {/if}
      </div>
    {:else if one.entry}
      <GlanceTiles placement={one.entry.key} widget={one.entry.widget} manifest={one.entry.manifest} options={one.entry.options} {onopen} />
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
    .dz-glances {
      display: flex;
      align-items: center;
      gap: var(--oc-space-1);
      padding: calc(var(--oc-space-1) / 2) var(--oc-space-2);
      box-sizing: border-box;
      overflow-x: auto;
    }

    .dz-glances--motion {
      position: relative;
      display: block;
      padding: 0;
    }

    .dz-gcell > :global(*) {
      width: max-content;
    }

    .dz-gpending {
      padding: var(--oc-space-1) var(--oc-space-2);
      border: var(--oc-border) dashed var(--oc-orange);
      border-radius: var(--oc-radius-sm);
      color: var(--oc-orange);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
      white-space: nowrap;
    }

    .dz-gwrap {
      display: inline-flex;
      gap: var(--oc-space-1);
    }
  }
</style>
