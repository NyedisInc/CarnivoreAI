<script lang="ts">
  const words = ['un', 'known'].join('');
  const rawId = ['session', 'row', 'id'].join('_');
</script>

<div class="oc-cellslot wh-probe" data-harness-cell style="width:200px;height:120px;">
  <div class="wh-probe-wide" data-probe="overflow-x">a row much wider than its cell</div>
  <div class="wh-probe-scroll" data-probe="scrollbar-x"><div class="wh-probe-inner">scrolls sideways</div></div>
  <p class="wh-probe-clip" data-probe="clipped-text">a long label cut off without an ellipsis at all</p>
  <p class="wh-probe-cut" data-probe="clipped-text-y">a line cut in half</p>
  <p data-probe="bad-text">state {words}, id {rawId}</p>
  <div class="wh-probe-stack" data-probe="overlap"><span>first label</span><span class="wh-probe-over">second label</span></div>
  <div class="wh-probe-tall" data-probe="overflow-y">slips out of the bottom of its cell</div>
</div>

<style>
  .wh-probe { display: block; color: var(--oc-text-primary); font-size: 12px; line-height: 16px; }
  .wh-probe-wide { width: 600px; }
  .wh-probe-scroll { overflow-x: auto; width: 180px; }
  .wh-probe-inner { width: 400px; }
  .wh-probe-clip { overflow: hidden; white-space: nowrap; width: 80px; margin: 0; }
  .wh-probe-cut { overflow: hidden; height: 7px; margin: 0; }
  .wh-probe-stack { position: relative; }
  .wh-probe-over { position: absolute; left: 4px; top: 0; }
  .wh-probe-tall { height: 200px; }
</style>
