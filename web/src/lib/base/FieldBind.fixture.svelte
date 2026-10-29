
<script lang="ts">
  import Field from './Field.svelte';

  let { seen }: { seen: Record<string, HTMLElement | null> } = $props();
  let plain: HTMLInputElement | HTMLTextAreaElement | null = $state(null);
  let area: HTMLInputElement | HTMLTextAreaElement | null = $state(null);
  let bare: HTMLInputElement | HTMLTextAreaElement | null = $state(null);
  let search: HTMLInputElement | HTMLTextAreaElement | null = $state(null);
  let legacy: HTMLInputElement | null = $state(null);

  $effect(() => {
    seen.plain = plain;
    seen.area = area;
    seen.bare = bare;
    seen.search = search;
    seen.legacy = legacy;
  });
</script>

<Field label="name" bind:element={plain} />
<Field label="note" multiline bind:element={area} />
<Field aria-label="bare" bind:element={bare} />
<Field variant="search" label="find" value="x" bind:element={search} bind:input={legacy} />
