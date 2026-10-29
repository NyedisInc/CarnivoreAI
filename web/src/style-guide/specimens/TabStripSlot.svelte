<script lang="ts">
  /* and the real */
  import TabStrip, { type TabItem } from '../../opscenter/shell/TabStrip.svelte';
  import CascadeMenu from '../../lib/drawer-tabs/CascadeMenu.svelte';
  import { useFrameHeader, type StripSlotProps } from '../../opscenter/shell/frame-header.svelte';
  import type { MenuNode } from '../../lib/drawer-tabs/add-component-menu';
  import type { AgentMarkFacts } from '../../lib/sessions/agent-marks';

  let { variant = 'desktop' }: { variant?: 'desktop' | 'touch' | 'dragging' } = $props();

  const seed: TabItem[] = [
    { id: 't:alpha', name: 'carnivore', family: 'claude', tint: null, face: agent('claude', 'working') },
    { id: 't:beta', name: 'music-service', family: 'codex', tint: '#4acf93', face: agent('codex', 'question') },
    { id: 't:gamma', name: 'scratch shell', family: 'shell', tint: null, face: agent('shell', 'idle', true) },
    { id: 't:delta', name: 'a very long session name that truncates', family: 'claude', tint: '#6cb0e0', face: agent('claude', 'finished_unread') },
  ];

  let items = $state<TabItem[]>(seed.map((item) => ({ ...item })));
  let active = $state('t:alpha');
  let newAnchor = $state<HTMLElement | null>(null);
  let iconAnchor = $state<HTMLElement | null>(null);
  let layout = $state('columns');

  function agent(family: string, status: string, unread = false): AgentMarkFacts {
    return { family, status, unread, startupGate: null, statusSource: 'registry', activityHint: null, transport: null };
  }

  const newMenu: MenuNode[] = [
    {
      id: 'p:music',
      label: 'music',
      children: [
        { id: 's:music-api', label: 'music-api', agent: agent('claude', 'idle'), run: () => (newAnchor = null) },
        { id: 's:music-ui', label: 'music-ui', agent: agent('codex', 'working'), run: () => (newAnchor = null) },
      ],
    },
    {
      id: 'p:carnivore',
      label: 'carnivore',
      children: [{ id: 's:docs', label: 'docs', agent: agent('claude', 'notice'), run: () => (newAnchor = null) }],
    },
    { id: 'n:new', label: 'new session', sep: true, run: () => (newAnchor = null) },
  ];

  const iconMenu = $derived<MenuNode[]>([
    {
      id: 'arrange',
      label: 'arrange',
      children: ['columns', 'rows', 'grid'].map((mode) => ({
        id: `arrange:${mode}`,
        label: mode,
        checked: layout === mode,
        run: () => {
          layout = mode;
        },
      })),
    },
    { id: 'done', label: 'close this menu', sep: true, run: () => (iconAnchor = null) },
  ]);

  function drop(id: string): void {
    items = items.filter((item) => item.id !== id);
    if (active === id) active = items[0]?.id ?? '';
  }

  const frameHeader = useFrameHeader();
  $effect(() => {
    if (!frameHeader) return;
    frameHeader.strip = strip;
    frameHeader.content = band;
    return () => {
      if (frameHeader.strip === strip) frameHeader.strip = null;
      if (frameHeader.content === band) frameHeader.content = null;
    };
  });
</script>


{#snippet band()}<div class="oc-tl-head-tabbed"></div>{/snippet}

{#snippet strip(_frame: StripSlotProps)}
  <TabStrip
    {items}
    {active}
    onSelect={(id) => (active = id)}
    onClose={drop}
    onKill={drop}
    onNew={(button) => (newAnchor = newAnchor ? null : button)}
    newOpen={newAnchor !== null}
    onIconClick={variant === 'touch' ? undefined : (button) => (iconAnchor = iconAnchor ? null : button)}
    menuOpen={iconAnchor !== null}
    touch={variant === 'touch'}
    group="sg-demo"
    dragging={variant === 'dragging' ? 't:gamma' : null}
    dropIndex={variant === 'dragging' ? 1 : null}
  />
{/snippet}

{#if !frameHeader}{@render strip({ onIconClick: () => {}, menuOpen: false, menuLabel: '' })}{/if}
{#if newAnchor}
  <CascadeMenu root={newMenu} anchor={newAnchor} label="add a tab" onClose={() => (newAnchor = null)} />
{/if}
{#if iconAnchor}
  <CascadeMenu root={iconMenu} anchor={iconAnchor} label="radio items" onClose={() => (iconAnchor = null)} />
{/if}
