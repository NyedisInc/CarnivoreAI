
<script lang="ts">
  import SortControl from '../../opscenter/ui/SortControl.svelte';
  import type { MenuNode } from '../drawer-tabs/add-component-menu';

  interface Props { label: string; options: readonly { value: string; label: string }[]; value: string; onChange: (next: string) => void }
  const { label, options, value, onChange }: Props = $props();
  const current = $derived(options.find((o) => o.value === value)?.label ?? value);
  const nodes = $derived<MenuNode[]>(options.map((o) => ({ id: o.value, label: o.label, checked: o.value === value, run: () => onChange(o.value) })));
</script>

<div class="oc-facet oc-facet--menu" data-facet="sort">
  <SortControl buttonText={`${label}: ${current}`} menuLabel={label} menu={nodes} />
</div>
