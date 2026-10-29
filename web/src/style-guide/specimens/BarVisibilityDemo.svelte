<script lang="ts">
  import ZoneHandle from '../../lib/zone-shell/ZoneHandle.svelte';
  import BarPin from '../../lib/widget-bars/BarPin.svelte';
  import GripPill from '../../lib/grip/GripPill.svelte';
</script>

<div class="sg-bv">
  <figure class="sg-bv__fig">
    <figcaption>right handle, 10px</figcaption>
    <div class="sg-bv__side"><ZoneHandle edge="side" /></div>
  </figure>
  <figure class="sg-bv__fig">
    <figcaption>bottom handle, 10px</figcaption>
    <div class="sg-bv__bottom"><ZoneHandle edge="bottom" /></div>
  </figure>
  <figure class="sg-bv__fig">
    <figcaption>bar pin, unpinned</figcaption>
    <div class="sg-bv__pin"><BarPin edge="side" /></div>
  </figure>
  <figure class="sg-bv__fig">
    <figcaption>grip pill, across and down</figcaption>
    <div class="sg-bv__grips"><GripPill axis="x" /><GripPill axis="y" /></div>
  </figure>
</div>

<style>
  .sg-bv {
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    align-items: flex-end;
  }

  .sg-bv__fig {
    margin: 0;
    min-width: 0;
  }

  .sg-bv__fig figcaption {
    margin-bottom: 4px;
    font: var(--oc-fs-micro) var(--font-mono);
    letter-spacing: 0.08em;
    color: var(--oc-text-secondary);
  }

  .sg-bv__side {
    width: 10px;
    height: 120px;
  }

  .sg-bv__bottom {
    width: 160px;
    height: 10px;
  }

  .sg-bv__pin,
  .sg-bv__grips {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 6px;
    background: var(--oc-rail-header-ground);
    box-shadow: inset 0 0 0 1px var(--oc-line-frame);
  }
</style>
