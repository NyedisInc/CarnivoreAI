<script lang="ts">
  import { huddle } from '../../../cplugs/huddle/huddle.svelte';
  import { holdDone } from '../../../cplugs/huddle/task-manager-done.svelte';
  import ListBody from './ListBody.svelte';
  import { statusRows } from './model';
  import { holdList } from './state.svelte';

  let { list, kind, hide = false, marked = false }: { list: string; kind: string; hide?: boolean; marked?: boolean } = $props();

  $effect(() => holdList());
  $effect(() => (kind === 'done' && !hide ? holdDone(list) : undefined));

  const rows = $derived(statusRows(huddle.groups, list, kind, hide, marked));
</script>

<ListBody {rows} density="compact" grouping="status" heads={false} />
