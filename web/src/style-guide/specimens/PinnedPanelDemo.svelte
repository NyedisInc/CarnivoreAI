<script lang="ts">
  import PinnedKeyBadge from '../../lib/widget-bars/PinnedKeyBadge.svelte';
</script>

<div class="sg-pp">
  <figure class="sg-pp__fig">
    <figcaption>pinned section, bottom panel (accent top edge, letter on its key)</figcaption>
    <div class="sg-pp__panel">
      <span class="sg-pp__edge sg-pp__edge--bottom"></span>
      <div class="sg-pp__strip"><span class="sg-pp__key sg-pp__key--on"><PinnedKeyBadge letter="A" /></span><span class="sg-pp__key"></span></div>
    </div>
  </figure>
  <figure class="sg-pp__fig">
    <figcaption>pinned section, side panel (accent left edge)</figcaption>
    <div class="sg-pp__panel sg-pp__panel--tall">
      <span class="sg-pp__edge sg-pp__edge--side"></span>
      <div class="sg-pp__strip sg-pp__strip--col"><span class="sg-pp__key sg-pp__key--on"><PinnedKeyBadge letter="L" /></span><span class="sg-pp__key"></span></div>
    </div>
  </figure>
  <figure class="sg-pp__fig">
    <figcaption>key letter, compact 16, cozy 28, detailed 32</figcaption>
    <div class="sg-pp__keys">
      {#each [16, 28, 32] as size (size)}
        <span class="sg-pp__key sg-pp__key--sized" style={`width:${size}px;height:${size}px`}><PinnedKeyBadge letter="M" compact={size === 16} /></span>
      {/each}
    </div>
  </figure>
</div>

<style>
  @layer components {
    .sg-pp {
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
      align-items: flex-end;
    }

    .sg-pp__fig {
      margin: 0;
      min-width: 0;
    }

    .sg-pp__fig figcaption {
      margin-bottom: 4px;
      font: var(--oc-fs-micro) var(--font-mono);
      letter-spacing: 0.08em;
      color: var(--oc-text-secondary);
    }

    .sg-pp__panel {
      position: relative;
      width: 220px;
      height: 56px;
      background: var(--oc-ground-panel);
      box-shadow: inset 0 0 0 1px var(--oc-line-frame);
    }

    .sg-pp__panel--tall {
      width: 56px;
      height: 140px;
    }

    .sg-pp__edge {
      position: absolute;
      background: var(--oc-orange);
    }

    .sg-pp__edge--bottom {
      top: 0;
      left: 0;
      right: 0;
      height: 2px;
    }

    .sg-pp__edge--side {
      top: 0;
      bottom: 0;
      left: 0;
      width: 2px;
    }

    .sg-pp__strip {
      position: absolute;
      inset: 0;
      display: flex;
      align-items: flex-end;
      gap: 6px;
      padding: 6px;
      min-width: 0;
    }

    .sg-pp__strip--col {
      flex-direction: column;
      align-items: flex-start;
    }

    .sg-pp__key {
      position: relative;
      flex: none;
      width: 20px;
      height: 20px;
      box-sizing: border-box;
      border: 1px solid transparent;
      border-radius: var(--oc-radius-sm);
    }

    .sg-pp__key--on {
      border-color: var(--oc-orange);
    }

    .sg-pp__keys {
      display: flex;
      gap: 16px;
      padding: 10px;
      background: var(--oc-rail-header-ground);
      box-shadow: inset 0 0 0 1px var(--oc-line-frame);
    }

    .sg-pp__key--sized {
      display: inline-block;
      border-color: var(--oc-line-frame);
    }
  }
</style>
