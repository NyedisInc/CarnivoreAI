<script lang="ts">
  import { renderMarkdown } from '../../sdk';

  let { source }: { source: string } = $props();
  let host = $state<HTMLElement | null>(null);

  $effect(() => {
    if (host) host.replaceChildren(renderMarkdown(source, host.ownerDocument));
  });
</script>

<div class="hdc-md" bind:this={host}></div>

<style>
  @layer components {
    .hdc-md { min-width: 0; overflow-wrap: anywhere; line-height: 1.5; }
    .hdc-md > :global(:first-child) { margin-top: 0; }
    .hdc-md > :global(:last-child) { margin-bottom: 0; }
    .hdc-md :global(h1),
    .hdc-md :global(h2),
    .hdc-md :global(h3),
    .hdc-md :global(h4),
    .hdc-md :global(h5),
    .hdc-md :global(h6) {
      margin: var(--oc-space-2) 0 var(--oc-space-1);
      color: var(--oc-text-bright);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    .hdc-md :global(p),
    .hdc-md :global(ul),
    .hdc-md :global(ol) { margin: var(--oc-space-1) 0; }
    .hdc-md :global(ul),
    .hdc-md :global(ol) { padding-left: calc(var(--oc-space-4) + var(--oc-space-0-5)); }
    .hdc-md :global(li > ul),
    .hdc-md :global(li > ol) { margin: 0; }
    .hdc-md :global(code) {
      padding: 0 var(--oc-pad-snug);
      border-radius: var(--oc-radius-control);
      background: var(--oc-ground-field);
      box-shadow: inset 0 0 0 1px var(--oc-line-rule);
    }
    .hdc-md :global(pre) {
      margin: var(--oc-space-1-5) 0;
      padding: var(--oc-space-1-5) var(--oc-space-2);
      overflow-x: auto;
      border-radius: var(--oc-radius-control);
      background: var(--oc-ground-field);
      box-shadow: inset 0 0 0 1px var(--oc-line-rule);
    }
    .hdc-md :global(pre code) { padding: 0; background: none; box-shadow: none; }
    .hdc-md :global(blockquote) {
      margin: var(--oc-space-1-5) 0;
      padding-left: var(--oc-space-2);
      border-left: 1px solid var(--oc-line-rule);
      color: var(--oc-text-secondary);
    }
    .hdc-md :global(hr) { margin: var(--oc-space-2) 0; border: 0; border-top: 1px solid var(--oc-line-rule); }
    .hdc-md :global(a) { color: var(--oc-cyan); }
  }
</style>
