<script lang="ts">
  import Icon from './Icon.svelte';

  let { name, showName = true }: { name: string; showName?: boolean } = $props();
</script>

<span class="oc-tier" title={showName ? undefined : name}>
  <Icon name="bot" size={14} />
  {#if showName}
    <span class="oc-tier-name">{name}</span>
  {:else}
    <span class="oc-visually-hidden">{name}</span>
  {/if}
</span>

<style>
  @layer components {
    .oc-tier {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-width: 0;
      color: var(--oc-text-primary);
    }

    .oc-tier-name {
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
  }
</style>
