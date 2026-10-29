<script lang="ts">
  import type { CellProps } from '../../lib/cell';
  import StubTab from '../../../lib/zone-shell/fixtures/StubTab.svelte';

  let props: CellProps = $props();
</script>

<StubTab name={props.instance} />
