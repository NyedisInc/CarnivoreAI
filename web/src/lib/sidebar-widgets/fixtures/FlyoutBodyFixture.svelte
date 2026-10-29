<script lang="ts">
  let open = $state(false);

  function onKeydown(event: KeyboardEvent): void {
    if (event.key !== 'Escape' || !open) return;
    event.preventDefault();
    open = false;
  }
</script>

<button data-base-exempt="test fixture, not shipped UI" type="button" data-fixture-dropdown aria-haspopup="menu" aria-expanded={open} onclick={() => (open = !open)} onkeydown={onKeydown}>more</button>
