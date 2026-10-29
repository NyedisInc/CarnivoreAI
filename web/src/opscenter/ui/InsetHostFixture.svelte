<script lang="ts">
  import { provideInset } from './page-inset';
  import Page from './Page.svelte';

  provideInset();
</script>

<Page title="hosts" count="3 items">
  {#snippet actions()}<button type="button" data-act>refresh</button>{/snippet}
  {#snippet bar()}<input data-field />{/snippet}
</Page>
