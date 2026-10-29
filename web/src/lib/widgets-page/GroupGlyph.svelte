<!-- the widgets page -->
<script lang="ts">
    import { glyphPath } from './group-glyphs';

    const { name, size = 12 }: { name: string; size?: number } = $props();
</script>

<svg viewBox="0 0 14 14" width={size} height={size} aria-hidden="true" focusable="false"><path d={glyphPath(name)} fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" /></svg>
