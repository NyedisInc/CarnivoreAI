<!-- the whole file -->
<script lang="ts">
    import type { Inline } from '../../opscenter/cells/notes/markdown';
    import { splitSkillMd } from './model';
    import { splitTables } from './md-tables';

    interface Props {
        text: string;
    }

    const { text }: Props = $props();

    const split = $derived(splitSkillMd(text));
    const pieces = $derived(splitTables(split.body));
</script>

{#snippet inline(nodes: Inline[])}
    {#each nodes as node, i (i)}
        {#if node.kind === 'text'}{node.text}
        {:else if node.kind === 'code'}<code>{node.text}</code>
        {:else if node.kind === 'break'}<br />
        {:else if node.kind === 'strong'}<strong>{@render inline(node.children)}</strong>
        {:else if node.kind === 'em'}<em>{@render inline(node.children)}</em>
        {:else}<a href={node.href} target="_blank" rel="noopener noreferrer">{@render inline(node.children)}</a>
        {/if}
    {/each}
{/snippet}

<div class="skp-fmt" data-skill-md-formatted>
    {#if split.front.length > 0}
        <dl class="skp-fm" data-skill-frontmatter>
            {#each split.front as entry, i (i)}
                <dt>{entry.key}</dt>
                <dd>{entry.value}</dd>
            {/each}
        </dl>
    {/if}
    {#each pieces as piece, p (p)}
      {#if piece.kind === 'table'}
        <div class="skp-fmt__tablewrap">
            <table class="skp-fmt__table" data-skill-md-table>
                <thead><tr>{#each piece.head as cell, c (c)}<th>{@render inline(cell)}</th>{/each}</tr></thead>
                <tbody>{#each piece.rows as row, r (r)}<tr>{#each row as cell, c (c)}<td>{@render inline(cell)}</td>{/each}</tr>{/each}</tbody>
            </table>
        </div>
      {:else}
      {#each piece.blocks as block, i (i)}
        {#if block.kind === 'heading'}
            <div class="skp-fmt__h skp-fmt__h{Math.min(block.level, 3)}" role="heading" aria-level={block.level + 2}>{@render inline(block.children)}</div>
        {:else if block.kind === 'paragraph'}
            <p>{@render inline(block.children)}</p>
        {:else if block.kind === 'code'}
            <pre class="skp-fmt__pre">{block.text}</pre>
        {:else if block.kind === 'quote'}
            <p class="skp-fmt__quote">{@render inline(block.children)}</p>
        {:else if block.kind === 'list'}
            {#if block.ordered}
                <ol>{#each block.items as item, j (j)}<li>{@render inline(item)}</li>{/each}</ol>
            {:else}
                <ul>{#each block.items as item, j (j)}<li>{@render inline(item)}</li>{/each}</ul>
            {/if}
        {:else}
            <hr class="skp-fmt__rule" />
        {/if}
      {/each}
      {/if}
    {/each}
</div>
