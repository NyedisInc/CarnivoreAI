<script lang="ts">
  import AnchoredPopup from '../AnchoredPopup.svelte';

  let props: Record<string, unknown> = $props();
</script>

<AnchoredPopup label="probe" onClose={() => {}} {...props} data-probe="">
  <button data-base-exempt="test fixture probe, not shipped UI" type="button" data-first>first</button>
  <button data-base-exempt="test fixture probe, not shipped UI" type="button" data-second>second</button>
</AnchoredPopup>
