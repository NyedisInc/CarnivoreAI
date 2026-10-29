<script lang="ts">
  import ZoneKeys from '../ZoneKeys.svelte';
  import { createZone } from '../zone.svelte';
  import type { KeyFace, TabRef } from '../zone-types';
  import type { WidgetManifest } from '../../../opscenter/widgets/types';

  let { editing = false, opened = [], flow = false, toggle = false, menu = true, counts = {}, globals = [] }: {
    editing?: boolean; opened?: string[]; flow?: boolean; toggle?: boolean; menu?: boolean; counts?: Record<string, number | null>; globals?: string[];
  } = $props();

  const manifest = { id: 'test.key', scope: 'global' } as unknown as WidgetManifest;
  const tabsOf = (...keys: string[]): TabRef[] => keys.map((key) => ({ key, kind: 'panel' }));
  const zones = [tabsOf('k1', 'k2'), tabsOf('k3')].map((tabs, s) => createZone({
    key: `test:keys:${s}`, tabs: () => tabs, active: () => null, select: () => {}, panel: () => 'closed', strip: 'keys', toolbar: 'none', menuHost: 'bar-key',
    ...(menu ? { openMenu: (tab: TabRef) => { menus.push(tab.key); } } : {}),
  }));
  export const menus: string[] = [];
  export const pressed: string[] = [];
  const face = (tab: TabRef): KeyFace => ({
    title: tab.key, ariaLabel: tab.key, tip: tab.key, label: tab.key, icon: 'file', ...(tab.key in counts ? { count: counts[tab.key] } : { badge: manifest }), global: globals.includes(tab.key), chip: false, letter: '', tone: 'oc-text-secondary',
  });
</script>

<ZoneKeys {zones} axis="y" ratio={0.5} labelAt="none" iconPx={16} compact={false} {editing} openKeys={new Set(opened)} {face} mark={null} empty={null} {flow} {toggle}
  onpress={(_zone, key) => pressed.push(key)} onedit={() => {}} ondragstart={() => {}} />
