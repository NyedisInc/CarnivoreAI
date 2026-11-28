
<script lang="ts">
    import { useRender } from './context';
    import { checkMarkdownSafeViolation } from './markdown-safe';
    import { parseMarkdownSafeAst, type MdBlock, type MdInline } from './markdown-safe-render';
    import { resolve, type UiNode } from './validate';

    const { node }: { node: Extract<UiNode, { type: 'markdown_safe' }> } = $props();
    const ctx = useRender();
    const text = $derived(String(resolve(node.value, ctx.data)));
    const violation = $derived(checkMarkdownSafeViolation(text));
    const blocks = $derived(violation === null ? parseMarkdownSafeAst(text) : []);
</script>

{#snippet renderInlines(inlines: MdInline[])}
    {#each inlines as inline}
        {#if inline.type === 'text'}{inline.text}
        {:else if inline.type === 'break'}<br />
        {:else if inline.type === 'code'}<code class="cu-md__code">{inline.text}</code>
        {:else if inline.type === 'safe_link_text'}<span class="cu-md__link">{inline.text}</span>
        {:else if inline.type === 'strong'}<strong class="cu-md__strong">{@render renderInlines(inline.children)}</strong>
        {:else if inline.type === 'em'}<em class="cu-md__em">{@render renderInlines(inline.children)}</em>
        {/if}
    {/each}
{/snippet}

{#snippet renderBlocks(list: MdBlock[])}
    {#each list as block}
        {#if block.type === 'heading'}
            {#if block.level === 1}<h1 class="cu-md__h" data-level="1">{@render renderInlines(block.inlines)}</h1>
            {:else if block.level === 2}<h2 class="cu-md__h" data-level="2">{@render renderInlines(block.inlines)}</h2>
            {:else if block.level === 3}<h3 class="cu-md__h" data-level="3">{@render renderInlines(block.inlines)}</h3>
            {:else if block.level === 4}<h4 class="cu-md__h" data-level="4">{@render renderInlines(block.inlines)}</h4>
            {:else if block.level === 5}<h5 class="cu-md__h" data-level="5">{@render renderInlines(block.inlines)}</h5>
            {:else}<h6 class="cu-md__h" data-level="6">{@render renderInlines(block.inlines)}</h6>
            {/if}
        {:else if block.type === 'paragraph'}
            <p class="cu-md__p">{@render renderInlines(block.inlines)}</p>
        {:else if block.type === 'code_block'}
            <pre class="cu-md__pre" data-language={block.language}><code class="cu-md__code">{block.text}</code></pre>
        {:else if block.type === 'blockquote'}
            <blockquote class="cu-md__quote">{@render renderBlocks(block.blocks)}</blockquote>
        {:else if block.type === 'list'}
            {#if block.ordered}
                <ol class="cu-md__list" start={block.start}>
                    {#each block.items as item}<li class="cu-md__item">{@render renderBlocks(item)}</li>{/each}
                </ol>
            {:else}
                <ul class="cu-md__list">
                    {#each block.items as item}<li class="cu-md__item">{@render renderBlocks(item)}</li>{/each}
                </ul>
            {/if}
        {:else if block.type === 'hr'}
            <hr class="cu-md__hr" />
        {/if}
    {/each}
{/snippet}

<div class="cu-md" data-cu="markdown_safe">
    {#if violation !== null}
        <p class="cu-md__refused" role="status">{ctx.t('cplug_ui.could_not_draw')}</p>
    {:else}
        {@render renderBlocks(blocks)}
    {/if}
</div>
