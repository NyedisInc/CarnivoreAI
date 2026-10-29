<script lang="ts">
  /* pop-out window */
  import CascadeMenu from '../drawer-tabs/CascadeMenu.svelte';
  import type { WidgetMenuCtx } from '../widget-menu/model';
  import { widgetMenuNodes } from '../item-menu/widget-nodes';
  import { declaredGroups } from '../widget-menu/declared-nodes';
  import { declaredActionsFor } from '../../opscenter/widgets/menu/declared-actions.svelte';

  let {
    hostId,
    extras = {},
    editing = false,
    anchor,
    label,
    onClose,
  }: {
    hostId: string;
    extras?: Pick<WidgetMenuCtx, 'focusMain' | 'close' | 'popOut' | 'header' | 'arrange' | 'editLayout' | 'settings'>;
    editing?: boolean;
    anchor: HTMLElement | null;
    label: string;
    onClose: () => void;
  } = $props();

  const root = $derived(widgetMenuNodes({ editing, onClose, content: declaredGroups(declaredActionsFor(hostId)), ...extras }));
</script>

<CascadeMenu {root} {anchor} {label} {onClose} />
