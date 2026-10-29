<script lang="ts">
  import Glyph from '../../lib/Glyph.svelte';
  import { GLYPHS } from '../../../../client/js/icons/glyphs.js';

  const names = Object.keys(GLYPHS).sort();
</script>

<ul class="sg-icon-grid">
  {#each names as name (name)}
    <li class="sg-icon-cell">
      <span class="sg-icon-row"><Glyph {name} /></span>
      <code>{name}</code>
    </li>
  {/each}
</ul>
