<script lang="ts">
  import { parseLine, parseMarkdown, type MdInline } from './task-manager-markdown';
  import TaskManagerCommandBox from './TaskManagerCommandBox.svelte';
  import { clipBlocks, clipInline } from './task-manager-markdown-clip';

  let { text, inline = false, limit = 0, more = false }: { text: string; inline?: boolean; limit?: number; more?: boolean } = $props();
  const blocks = $derived(inline ? [] : clipBlocks(parseMarkdown(text), limit, more));
  const line = $derived(inline ? clipInline(parseLine(text), limit, more).nodes : []);
</script>

{#snippet runs(nodes: MdInline[])}{#each nodes as node, at (at)}{#if node.t === 'text'}{node.v}{:else if node.t === 'strong'}<strong>{@render runs(node.c)}</strong>{:else if node.t === 'em'}<em>{@render runs(node.c)}</em>{:else if node.t === 'code'}<code class="hmd-code">{node.v}</code>{:else}<a class="hmd-link" href={node.href} target="_blank" rel="noopener noreferrer">{@render runs(node.c)}</a>{/if}{/each}{/snippet}

{#if inline}<span class="hmd-line" data-task-manager-md data-task-manager-md-inline>{@render runs(line)}</span>{:else}
<div class="hmd" data-task-manager-md>
  {#each blocks as block, at (at)}
    {#if block.t === 'paragraph'}
      <p class="hmd-p">{#each block.lines as line, i (i)}{#if i > 0}<br />{'\n'}{/if}{@render runs(line)}{/each}</p>
    {:else if block.t === 'heading'}
      <div class="hmd-h hmd-h--{block.level}" role="heading" aria-level={block.level + 2}>{@render runs(block.c)}</div>
    {:else if block.t === 'code'}
      <TaskManagerCommandBox text={block.text} copyText={block.full} lang={block.lang} />
    {:else if block.t === 'list'}
      <svelte:element this={block.ordered ? 'ol' : 'ul'} class="hmd-list" start={block.ordered && block.start !== 1 ? block.start : undefined}>
        {#each block.items as item, i (i)}
          <li>{@render runs(item.c)}
            {#if item.sub}
              <svelte:element this={item.sub.ordered ? 'ol' : 'ul'} class="hmd-list">
                {#each item.sub.items as sub, j (j)}<li>{@render runs(sub)}</li>{/each}
              </svelte:element>
            {/if}
          </li>
        {/each}
      </svelte:element>
    {:else if block.t === 'table'}
      <div class="hmd-scroll" data-task-manager-md-table>
        <table class="hmd-table">
          <thead><tr>{#each block.head as cell, c (c)}<th class="hmd-cell--{block.align[c]}">{@render runs(cell)}</th>{/each}</tr></thead>
          <tbody>
            {#each block.rows as row, r (r)}
              <tr>{#each row as cell, c (c)}<td class="hmd-cell--{block.align[c]}">{@render runs(cell)}</td>{/each}</tr>
            {/each}
          </tbody>
        </table>
      </div>
    {:else}
      <dl class="hmd-kv" data-task-manager-md-kv>
        {#each block.pairs as pair, i (i)}<dt>{pair.k}</dt><dd>{@render runs(pair.v)}</dd>{/each}
      </dl>
    {/if}
  {/each}
</div>
{/if}

<style>
  @layer components {
    .hmd {
      display: flex;
      flex-direction: column;
      gap: 6px;
      min-width: 0;
      white-space: normal;
      overflow-wrap: anywhere;
    }

    .hmd-line {
      display: inline;
      min-width: 0;
    }

    .hmd-p,
    .hmd-list,
    .hmd-pre,
    .hmd-kv {
      margin: 0;
    }

    .hmd-h {
      color: var(--oc-text-secondary);
      font-family: var(--font-mono);
      font-size: 0.85em;
      font-weight: 600;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }

    .hmd-h--1 {
      color: var(--oc-text-primary);
    }

    .hmd-list {
      padding-left: 20px;
    }

    .hmd-list .hmd-list {
      margin-top: 2px;
    }

    .hmd-code,
    .hmd-pre {
      font-family: var(--font-mono);
      font-size: 0.92em;
    }

    .hmd-code {
      padding: 0 4px;
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-hover);
    }

    .hmd-pre {
      padding: 6px 8px;
      overflow-x: auto;
      border: 1px solid var(--oc-line-faint);
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-hover);
      white-space: pre;
    }

    .hmd-link {
      color: var(--oc-cyan);
      text-decoration: underline;
    }

    .hmd-scroll {
      max-width: 100%;
      overflow-x: auto;
    }

    .hmd-table {
      border-collapse: collapse;
      font-size: 0.95em;
    }

    .hmd-table th,
    .hmd-table td {
      padding: 3px 12px 3px 0;
      box-shadow: inset 0 -1px 0 var(--oc-line-faint);
      white-space: nowrap;
      vertical-align: top;
    }

    .hmd-table th {
      color: var(--oc-text-secondary);
      font-family: var(--font-mono);
      font-size: 0.85em;
      font-weight: 600;
      letter-spacing: 0.06em;
      text-align: left;
      text-transform: uppercase;
    }

    .hmd-cell--left {
      text-align: left;
    }

    .hmd-cell--center {
      text-align: center;
    }

    .hmd-table th.hmd-cell--right,
    .hmd-table td.hmd-cell--right {
      padding-right: 0;
      padding-left: 12px;
      font-variant-numeric: tabular-nums;
      text-align: right;
    }

    .hmd-kv {
      display: grid;
      grid-template-columns: max-content minmax(0, 1fr);
      gap: 2px 12px;
    }

    .hmd-kv dt {
      color: var(--oc-text-secondary);
      font-family: var(--font-mono);
      font-size: 0.9em;
    }

    .hmd-kv dd {
      margin: 0;
    }
  }
</style>
