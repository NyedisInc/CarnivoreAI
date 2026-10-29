<script lang="ts">
  import WidgetHead from '../../opscenter/shell/WidgetHead.svelte';
  import CornerMenu from '../../opscenter/shell/CornerMenu.svelte';
  import DeclaredTabMenu from '../zone-shell/DeclaredTabMenu.svelte';
  import type { FrameHeader } from '../../opscenter/shell/frame-header.svelte';
  import type { MenuSlot } from '../../opscenter/shell/widget-head';
  import type { CellMeta } from '../../opscenter/engine/types';

  let { header, meta, title, phone = false, onClose }: {
    header: FrameHeader;
    meta: CellMeta;
    title: string;
    phone?: boolean;
    onClose: () => void;
  } = $props();
</script>

{#snippet menu(slot: MenuSlot)}
  <DeclaredTabMenu hostId={header.hostId} extras={{ close: { run: onClose } }} anchor={slot.anchor} label={title} onClose={slot.close} />
{/snippet}
{#snippet corner()}
  <CornerMenu {meta} {title} editing={false} place="row" {phone} {menu} />
{/snippet}
<WidgetHead {meta} {header} {title} {corner} tap={phone} withRight={false} onClose={() => onClose()} />
