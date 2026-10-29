<script lang="ts">
  /* <script */
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
      margin: 8px 0 4px;
      color: var(--oc-text-bright);
      font-size: var(--oc-fs-label);
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    .hdc-md :global(p),
    .hdc-md :global(ul),
    .hdc-md :global(ol) { margin: 4px 0; }
    .hdc-md :global(ul),
    .hdc-md :global(ol) { padding-left: 18px; }
    .hdc-md :global(code) {
      padding: 0 3px;
      border-radius: 2px;
      background: var(--oc-ground-field);
      box-shadow: inset 0 0 0 1px var(--oc-line-rule);
    }
    .hdc-md :global(pre) {
      margin: 6px 0;
      padding: 6px 8px;
      overflow-x: auto;
      border-radius: 2px;
      background: var(--oc-ground-field);
      box-shadow: inset 0 0 0 1px var(--oc-line-rule);
    }
    .hdc-md :global(pre code) { padding: 0; background: none; box-shadow: none; }
    .hdc-md :global(blockquote) {
      margin: 6px 0;
      padding-left: 8px;
      border-left: 1px solid var(--oc-line-rule);
      color: var(--oc-text-secondary);
    }
    .hdc-md :global(hr) { margin: 8px 0; border: 0; border-top: 1px solid var(--oc-line-rule); }
    .hdc-md :global(a) { color: var(--oc-cyan); }
  }
</style>
