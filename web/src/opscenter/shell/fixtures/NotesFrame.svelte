<script lang="ts">
  import CellFrame from '../CellFrame.svelte';
  import NotesCell from '../../cells/notes/Cell.svelte';
  import { META } from '../../engine/meta';
  import { terminalLayout } from '../../engine/layout.svelte';
</script>
<CellFrame meta={META.notes} instance="notes" widthState="wide" heightState="full" store={terminalLayout}>
  {#snippet body()}
    <NotesCell width={480} height={400} meta={META.notes} instance="notes" />
  {/snippet}
</CellFrame>
