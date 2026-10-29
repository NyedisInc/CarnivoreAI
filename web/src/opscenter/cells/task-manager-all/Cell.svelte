<script lang="ts">
  import HuddleBody from '../../../cplugs/huddle/HuddleBody.svelte';
  import { AGGREGATE } from '../../../cplugs/huddle/huddle-model';
</script>

<div class="oc-hdl-all" data-task-manager-all-cell>
  <HuddleBody list={AGGREGATE} />
</div>

<style>
  @layer components {
    .oc-hdl-all { display: flex; flex-direction: column; height: 100%; min-height: 0; }
  }
</style>
