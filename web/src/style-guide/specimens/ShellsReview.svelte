
<script lang="ts">
  import CellFrameDemo from './CellFrameDemo.svelte';
  import Modals from './Modals.svelte';
  import OpsPrimitives from './OpsPrimitives.svelte';
  import SettingsFormDemo from './SettingsFormDemo.svelte';
</script>

<div class="sg-bc__group" data-review-shells>
  <span class="sg-bc__label">shells on the base: the real shells, live</span>
  <div class="sg-review-shells">
    <div class="sg-qc-col" data-review-shell="widget">
      <span class="sg-bc__label">widget shell and head (open its menu from the head icon)</span>
      <CellFrameDemo slot="notes" />
    </div>
    <div class="sg-qc-col" data-review-shell="menu">
      <span class="sg-bc__label">menu (press sort)</span>
      <OpsPrimitives part="sort" />
    </div>
    <div class="sg-qc-col" data-review-shell="dialog">
      <span class="sg-bc__label">dialogs (each button opens the real one)</span>
      <Modals />
    </div>
    <div class="sg-qc-col" data-review-shell="settings">
      <span class="sg-bc__label">settings form</span>
      <SettingsFormDemo />
    </div>
  </div>
</div>
