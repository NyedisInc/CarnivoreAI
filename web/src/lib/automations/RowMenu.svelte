
<script lang="ts">
  import CascadeMenu from '../drawer-tabs/CascadeMenu.svelte';
  import type { MenuNode } from '../drawer-tabs/add-component-menu';
  import { t } from '../i18n/index.svelte';
  import { automationMenuNodes, type RowMenuAction } from './row-menu-nodes';
  import { untrack } from 'svelte';

  let { anchor, onPick, onClose }: { anchor: HTMLElement; onPick: (action: RowMenuAction) => void; onClose: () => void } = $props();

  const anchorEl = untrack(() => anchor);

  const nodes = $derived<MenuNode[]>(automationMenuNodes(onPick));
</script>

<CascadeMenu root={nodes} anchor={anchorEl} label={t('automations.page.menu.aria')} alignEnd {onClose} />
