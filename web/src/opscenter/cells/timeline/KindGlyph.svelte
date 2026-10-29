<script lang="ts">
  /*  hidden  */
  let { kind, off = false }: { kind: 'compact' | 'bookmark' | 'restart' | 'restore' | 'sleep'; off?: boolean } = $props();
</script>

<span class="tlx-glyph" data-kind={kind} data-off={off || undefined} aria-hidden="true"></span>

<style>
  @layer components {
    .tlx-glyph {
      position: relative;
      display: inline-block;
      flex: 0 0 auto;
      width: 0.625rem;
      height: 0.625rem;
      vertical-align: middle;
    }

    .tlx-glyph::before {
      content: '';
      position: absolute;
      inset: 0.0625rem;
      box-sizing: border-box;
      background: var(--_hue);
    }

    .tlx-glyph[data-kind='compact'] { --_hue: var(--oc-violet); }
    .tlx-glyph[data-kind='compact']::before { inset: 0.125rem; transform: rotate(45deg); }
    .tlx-glyph[data-kind='bookmark'] { --_hue: var(--oc-yellow); }
    .tlx-glyph[data-kind='bookmark']::before { inset: 0 0.1875rem 0 0.1875rem; clip-path: polygon(0 0, 100% 0, 100% 70%, 50% 52%, 0 70%); }
    .tlx-glyph[data-kind='restart'] { --_hue: var(--oc-green); }
    .tlx-glyph[data-kind='restart']::before { border: 0.125rem solid var(--_hue); border-radius: 50%; background: none; }
    .tlx-glyph[data-kind='restore'] { --_hue: var(--oc-cyan); }
    .tlx-glyph[data-kind='restore']::before { border: var(--oc-border) solid var(--_hue); background: none; }
    .tlx-glyph[data-kind='sleep'] { --_hue: var(--oc-text-dim); }
    .tlx-glyph[data-kind='sleep']::before {
      inset: 0.0625rem 0;
      background: repeating-linear-gradient(135deg, transparent 0 0.125rem, var(--_hue) 0.125rem 0.1875rem);
      box-shadow: inset 0 0 0 var(--oc-border) var(--oc-line-panel);
    }

    .tlx-glyph[data-off] { --_hue: var(--oc-text-dim); opacity: 0.6; }
    .tlx-glyph[data-off][data-kind='compact']::before,
    .tlx-glyph[data-off][data-kind='bookmark']::before { background: none; box-shadow: inset 0 0 0 var(--oc-border) var(--_hue); }
  }
</style>
