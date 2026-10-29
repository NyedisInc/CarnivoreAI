<script lang="ts">
  let { blank = false }: { blank?: boolean } = $props();
</script>

<div class="oc-cellslot wh-defect" data-harness-cell style="width:360px;height:240px;">
  {#if blank}
    <span class="wh-defect-bar"></span>
  {:else}
    <div class="wh-defect-row wh-defect-overlap"><span>first label</span><span class="wh-defect-over">second label</span></div>
    <div class="wh-defect-row wh-defect-graphic"><span class="wh-defect-figure">8</span><span class="wh-defect-bar wh-defect-on-figure"></span></div>
    <p class="wh-defect-row wh-defect-clipped">a long label cut off without an ellipsis at all</p>
    <p class="wh-defect-row wh-defect-ellipsis">a long label cut off with an ellipsis at the end</p>
    <p class="wh-defect-truncatable wh-defect-ellipsis wh-defect-row" data-fit-truncate>a long field the widget says it may truncate</p>
    <p class="wh-defect-row wh-defect-tiny">tiny print</p>
    <p class="wh-defect-row wh-defect-contrast">hard to read</p>
    <p class="wh-defect-decor wh-defect-contrast wh-defect-row" aria-hidden="true">decorative and dim</p>
    <p class="wh-defect-row wh-defect-wrap" data-fit-single-line>two words</p>
    <p class="wh-defect-row wh-defect-clean">a clean label</p>
    <div class="wh-defect-escape">spills out</div>
  {/if}
</div>

<style>
  @layer components {
    .wh-defect { display: block; position: relative; color: var(--oc-text-primary); background: var(--oc-ground-panel); font-family: var(--font-mono); font-size: 12px; line-height: 16px; }
    .wh-defect-row { position: relative; margin: 0; height: 18px; }
    .wh-defect-over { position: absolute; left: 4px; top: 0; }
    .wh-defect-figure { font-size: 20px; line-height: 18px; }
    .wh-defect-bar { display: inline-block; width: 40px; height: 14px; background: var(--oc-spark); }
    .wh-defect-on-figure { position: absolute; left: 0; top: 2px; }
    .wh-defect-clipped, .wh-defect-ellipsis { width: 80px; overflow: hidden; white-space: nowrap; }
    .wh-defect-ellipsis { text-overflow: ellipsis; }
    .wh-defect-tiny { font-size: 7px; }
    .wh-defect-contrast { color: color-mix(in srgb, var(--oc-ground-panel) 92%, var(--oc-text-bright)); }
    .wh-defect-wrap { width: 40px; height: auto; }
    .wh-defect-escape { position: absolute; right: -40px; bottom: 4px; width: 80px; }
  }
</style>
