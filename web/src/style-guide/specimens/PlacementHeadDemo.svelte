<script lang="ts">
  import PlacementHead from '../../opscenter/shell/PlacementHead.svelte';
  import { createFrameHeader } from '../../opscenter/shell/frame-header.svelte';
  import { META } from '../../opscenter/engine/meta';
  import { t } from '../../lib/i18n/index.svelte';
  import { manifestById } from '../../opscenter/widgets/core-manifests';
  import PlacementMenuHost from '../../lib/zone-shell/PlacementMenuHost.svelte';
  import type { MenuSlot } from '../../opscenter/shell/widget-head';

  const header = createFrameHeader('style-guide:placement-head');
  const shown = true;
</script>

{#snippet menu(slot: MenuSlot)}
  <PlacementMenuHost
    host="drawer-card"
    bodyHost="drawer"
    manifest={manifestById('core.activity-log')!}
    placementKey="core.activity-log"
    extras={{ header: { shown, toggle: () => {} }, close: { run: () => {} } }}
    anchor={slot.anchor}
    label={t('opscenter.frame.options', { title: t(META['activity-log'].titleKey) })}
    onClose={slot.close}
  />
{/snippet}


<div class="sg-drawer-host" style="container: oc-head / inline-size">
  <PlacementHead
    meta={META['activity-log']}
    {header}
    title={t(META['activity-log'].titleKey)}
    {shown}
    onRemove={() => {}}
    {menu}
  />
</div>
