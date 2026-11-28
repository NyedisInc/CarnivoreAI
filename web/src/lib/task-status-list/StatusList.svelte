<script lang="ts">
  /* the Task Manager */
  import { huddle } from '../../plugins/taskmanager/huddle.svelte';
  import { holdDone } from '../../plugins/taskmanager/task-manager-done.svelte';
  import ListBody from './ListBody.svelte';
  import { statusRows } from './model';
  import { holdList } from './state.svelte';

  let { list, kind, hide = false, marked = false }: { list: string; kind: string; hide?: boolean; marked?: boolean } = $props();

  $effect(() => holdList());
  $effect(() => (kind === 'done' && !hide ? holdDone(list) : undefined));

  const rows = $derived(statusRows(huddle.groups, list, kind, hide, marked));
</script>

<ListBody {rows} density="compact" grouping="status" heads={false} />
