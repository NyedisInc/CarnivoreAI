<script lang="ts">
  import NotesCell from '../../opscenter/cells/notes/Cell.svelte';
  import { META } from '../../opscenter/engine/meta';
  import { viewport } from '../../opscenter/engine/viewport.svelte';
  import IconButton from '../base/IconButton.svelte';
  import { useFrameHeader, useHeaderGroup } from '../../opscenter/shell/frame-header.svelte';
  import { declareWidgetActions } from '../../opscenter/widgets/menu/declared-actions.svelte';
  import RightDrawerHead from '../right-drawer/RightDrawerHead.svelte';
  import { t } from '../i18n/index.svelte';

  let { onClose, onComponent, canComponent }: {
    onClose: () => void;
    onComponent: () => void;
    canComponent: () => boolean;
  } = $props();

  const DRAWER_SOURCE = 'right-drawer';

  const header = useFrameHeader()!;

  let tick = $state(0);
  $effect(() => {
    const bump = (): void => { tick += 1; };
    window.addEventListener('resize', bump);
    return () => window.removeEventListener('resize', bump);
  });
  const componentShown = $derived.by(() => {
    void tick;
    return canComponent();
  });

  useHeaderGroup(() => (componentShown ? asComponent : null));

  $effect(() => declareWidgetActions(header.hostId, DRAWER_SOURCE, [{
    id: 'as-component',
    label: t('opscenter.cell.notes.as_component'),
    blocked: componentShown ? undefined : t('opscenter.cell.notes.as_component_blocked'),
    group: DRAWER_SOURCE,
    run: () => onComponent(),
  }]));

  let bodyWidth = $state(0);
  let bodyHeight = $state(0);
</script>

{#snippet asComponent()}
  <IconButton label={t('opscenter.cell.notes.as_component')} variant="quiet" icon="components" iconSize={15}
    data-notes-drawer="as-component" onclick={() => onComponent()} />
{/snippet}

<div class="nd-frame">
  <RightDrawerHead {header} meta={META.notes} title={t('opscenter.cell.notes.drawer')} phone={viewport.phone} {onClose} />
  <div class="nd-body" bind:clientWidth={bodyWidth} bind:clientHeight={bodyHeight}>
    <NotesCell width={bodyWidth || 320} height={bodyHeight || 420} meta={META.notes} instance="notes" phone={true} />
  </div>
</div>

<style>
  .nd-frame {
    display: flex;
    flex: 1 1 auto;
    flex-direction: column;
    min-width: 0;
    min-height: 0;
    container: oc-head / inline-size;
  }

  .nd-body {
    display: flex;
    flex: 1 1 auto;
    flex-direction: column;
    min-height: 0;
  }
</style>
