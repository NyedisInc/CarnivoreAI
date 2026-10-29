<script lang="ts">
  import { useFrameHeader } from '../../../opscenter/shell/frame-header.svelte';
  import { declareWidgetActions } from '../../../opscenter/widgets/menu/declared-actions.svelte';

  const header = useFrameHeader();
  $effect(() => (header ? declareWidgetActions(header.hostId, 'frame', [{ id: 'preview', label: 'preview', run: () => {} }]) : undefined));
</script>

<p data-notes-stub>notes</p>
