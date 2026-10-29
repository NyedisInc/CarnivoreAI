<script lang="ts">
  import SortControl from '../../opscenter/ui/SortControl.svelte';
  import { useFrameHeader } from '../../opscenter/shell/frame-header.svelte';
  import type { MenuNode } from '../../lib/drawer-tabs/add-component-menu';
  import { t } from '../../lib/i18n/index.svelte';

  const menu: MenuNode[] = [{ id: 'name', label: t('opscenter.projects.sort.name'), run: () => undefined }];
  const frameHeader = useFrameHeader();
  $effect(() => {
    if (!frameHeader?.drawn) return;
    frameHeader.action = sortGroup;
    return () => { frameHeader.action = null; };
  });
</script>

{#snippet sortGroup()}
  <SortControl
    buttonText={t('opscenter.projects.sort.button', { label: t('opscenter.projects.sort.name') })}
    menuLabel={t('opscenter.projects.sort.menu')}
    {menu}
  />
{/snippet}
