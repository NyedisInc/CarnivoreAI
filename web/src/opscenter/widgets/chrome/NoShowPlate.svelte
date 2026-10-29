<script lang="ts">
  import WidgetIcon from '../../ui/WidgetIcon.svelte';

  let { icon, widget, title }: { icon: string; widget: string; title: string } = $props();
</script>

<div class="oc-noshow" data-no-show title={title} role="img" aria-label={title}>
  <WidgetIcon name={icon} {widget} size={14} />
  <span class="oc-noshow-name">{title}</span>
</div>

<style>
  @layer components {
    .oc-noshow {
      height: 100%;
      min-width: 0;
      min-height: 0;
      display: flex;
      flex-wrap: wrap;
      align-content: center;
      justify-content: center;
      gap: var(--oc-space-1);
      overflow: hidden;
      color: var(--oc-text-dim);
      font-family: var(--oc-font);
      font-size: var(--oc-fs-hint);
      text-transform: lowercase;
    }
    .oc-noshow-name {
      min-width: 0;
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }
</style>
