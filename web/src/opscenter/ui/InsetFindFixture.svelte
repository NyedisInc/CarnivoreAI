
<script lang="ts">
  import { provideInset } from './page-inset';
  import Page from './Page.svelte';

  provideInset();
</script>

<Page title="hosts" frame="column">
  {#snippet find()}<input id="f" data-field />{/snippet}
  <p>body</p>
</Page>
