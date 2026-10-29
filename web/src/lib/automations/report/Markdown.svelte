
<script lang="ts">
  import { parseMarkdown, type Inline } from '../logic/markdown';

  let { src }: { src: string } = $props();
  const blocks = $derived(parseMarkdown(src));
</script>

{#snippet inline(spans: Inline[])}{#each spans as s, i (i)}{#if s.type === 'code'}<code>{s.text}</code>{:else if s.type === 'bold'}<b>{s.text}</b>{:else}{s.text}{/if}{/each}{/snippet}

<div class="r-md">
  {#each blocks as b, i (i)}
    {#if b.type === 'code'}
      <pre class="r-code">{b.text}</pre>
    {:else if b.type === 'heading'}
      <h4 class="r-mh" data-level={b.level}>{@render inline(b.children)}</h4>
    {:else if b.type === 'ul'}
      <ul>{#each b.items as it, j (j)}<li>{@render inline(it)}</li>{/each}</ul>
    {:else if b.type === 'ol'}
      <ol>{#each b.items as it, j (j)}<li>{@render inline(it)}</li>{/each}</ol>
    {:else if b.type === 'table'}
      <div class="r-scroll">
        <table class="r-table">
          <thead><tr>{#each b.head as c, j (j)}<th>{@render inline(c)}</th>{/each}</tr></thead>
          <tbody>
            {#each b.rows as row, j (j)}
              <tr>{#each row as c, k (k)}<td>{@render inline(c)}</td>{/each}</tr>
            {/each}
          </tbody>
        </table>
      </div>
    {:else}
      <p>{#each b.lines as line, j (j)}{#if j > 0}<br />{/if}{@render inline(line)}{/each}</p>
    {/if}
  {/each}
</div>
