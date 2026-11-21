<script lang="ts">
  import { t } from '../sdk';
  import type { MenuNode } from '../sdk';
  import PointerMenu from './PointerMenu.svelte';

  interface Props {
    at: { x: number; y: number };
    label: string;
    onshow: () => void;
    oncopy: () => void;
    onclose: () => void;
  }

  const { at, label, onshow, oncopy, onclose }: Props = $props();

  const nodes = $derived<MenuNode[]>([
    { id: 'show', label: t('cplug.devwidgetlab.tree.menu.show'), icon: 'eye', run: () => { onclose(); onshow(); } },
    { id: 'copy-key', label: t('cplug.devwidgetlab.tree.menu.copy_key'), icon: 'copy', run: () => { onclose(); oncopy(); } },
  ]);
</script>

<PointerMenu {at} label={t('cplug.devwidgetlab.tree.menu.label', { name: label })} {nodes} {onclose} />
