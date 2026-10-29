<script lang="ts">
  import AnchoredPopup from '../AnchoredPopup.svelte';

  let props: Record<string, unknown> = $props();
</script>

<AnchoredPopup label="probe" onClose={() => {}} {...props} data-probe="">
  <button type="button" data-first>first</button>
  <button type="button" data-second>second</button>
</AnchoredPopup>
