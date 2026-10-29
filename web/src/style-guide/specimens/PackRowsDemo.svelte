<script lang="ts">
  import PackSection from '../../lib/sidebar-shell/PackSection.svelte';
  import type { PackMachine } from '../../lib/pack-machines/pack-machines-store.svelte';
  import type { PackPlan } from '../../lib/sidebar-shell/plan';

  const snap = (cpu: number, mem: number, disk: number): PackMachine['snapshot'] =>
    ({
      load: { cores: 10, load_1: cpu, memory_percent: mem, disk_percent: disk },
      reserve: { level: 'in_use', cpu_pct: 30, mem_pct: 20, source: 'schedule' },
    }) as unknown as PackMachine['snapshot'];
  const machine = (id: string, over: Partial<PackMachine>): PackMachine => ({
    install_id: id, label: id, is_self: false, is_master: false, paired: true, state: 'connected', capabilities: [],
    specs: { model: 'quartz', cores: 10, mem_total_gb: 16 }, snapshot: snap(5, 58, 40), age_seconds: 2, ...over,
  });
  const led = (inner: string, outer: string): string =>
    `<span class="status-led" data-inner="${inner}" data-outer="${outer}" role="img" aria-label="${inner}"></span>`;
  const rows = [
    { m: machine('willow', { is_self: true, is_master: true, state: 'self' }), light: led('working', 'active') },
    { m: machine('orchard', { snapshot: snap(8, 81, 93) }), light: led('idle', 'steady') },
    { m: machine('sulaco', { state: 'stale', snapshot: null }), light: led('unknown', 'dim') },
  ];
  const plan = (density: string): PackPlan => ({
    type: 'pack', key: 'pack', open: true, density, count: rows.length,
    heading: { toggle: 'group', key: 'pack', bandKind: 'reserved', expanded: true, bodyId: `sg-pack-body-${density}`, title: 'collapse the pack section',
      label: 'pack', iconHtml: '', ledHtml: '', pickedIconHtml: '', rollupHtml: '' },
    rows: rows.map(({ m, light }) => ({ id: m.install_id, label: m.label, alpha: m.is_master, self: m.is_self,
      link: m.is_self ? null : m.snapshot ? 'linked' : 'down', machine: m, off: m.label === 'sulaco', lightHtml: light })),
  });
</script>

{#each ['compact', 'cozy', 'detailed'] as density (density)}
  <div class="session-sidebar-panel" data-density={density} style="position: static; transform: none; visibility: visible; width: auto; max-width: 320px; margin-bottom: 12px; padding: 8px 0">
    <PackSection p={plan(density)} />
  </div>
{/each}
