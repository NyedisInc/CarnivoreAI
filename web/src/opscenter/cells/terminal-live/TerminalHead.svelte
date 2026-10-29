<script lang="ts">
  import { untrack, type Snippet } from 'svelte';
  import { inputFocus } from '../../lib/input-focus.svelte';
  import { useFrameHeader, useHeaderGroup, useTabPane } from '../../shell/frame-header.svelte';
  import TerminalUtilities from './TerminalUtilities.svelte';
  import LayoutCellMarks from '../../layouts/LayoutCellMarks.svelte';
  import { toggleWidthFor } from '../../layouts/broadcast.svelte';
  import PromptHeader from '../../../lib/terminal-search/PromptHeader.svelte';
  import { cellSearchFor } from '../../../lib/terminal-search/cell-search';
  import { terminalSearchController } from '../../../lib/terminal-search/mount-search';
  import { isPrimaryInstance } from '../terminal/meta';
  import type { StatusHue } from '../../api';
  import { showsStatusLight } from '../../../lib/sessions/agent-marks';

  let {
    hue,
    sessionId,
    controller,
    slot,
    width = 0,
    name,
    statusWord = '',
    showsStatusWord = true,
    measured = true,
    tail,
    agentFamily = null,
  }: {
    sessionId: string;
    controller: unknown;
    slot: string;
    width?: number;
    hue: StatusHue;
    name: string;
    statusWord?: string;
    showsStatusWord?: boolean;
    measured?: boolean;
    tail?: Snippet;
    agentFamily?: string | null;
  } = $props();

  const frameHeader = useFrameHeader();
  const tabPane = useTabPane();
  const showsHead = $derived(!tabPane || tabPane.active);
  const framed = $derived(!!frameHeader?.drawn);
  const widgetForm = $derived(!!tabPane && !!frameHeader && frameHeader.gridSlot === null);
  const toolsUp = useHeaderGroup(() => (widgetForm && showsHead ? widgetTools : null), true);
  const rowToken = Symbol('terminal-head-rowless');
  $effect(() => {
    const rail = tabPane && !widgetForm && showsHead ? barSearch?.rail : null;
    if (!rail) return;
    untrack(() => rail.retain());
    return () => untrack(() => rail.release());
  });
  $effect(() => {
    if (!frameHeader || !framed || !showsHead || widgetForm) return;
    if (tabPane) frameHeader.tools = toolsContent;
    if (tabPane && !rowHasContent) {
      frameHeader.rowless = rowToken;
      return () => {
        if (frameHeader.tools === toolsContent) frameHeader.tools = null;
        if (frameHeader.rowless === rowToken) frameHeader.rowless = null;
      };
    }
    frameHeader.content = headerContent;
    return () => {
      if (frameHeader.content === headerContent) frameHeader.content = null;
      if (frameHeader.tools === toolsContent) frameHeader.tools = null;
    };
  });

  const search = $derived.by(() => {
    if (!tabPane) return null;
    void controller;
    return isPrimaryInstance(slot) ? terminalSearchController() : cellSearchFor(slot);
  });
  let lastSearch: typeof search = null;
  const barSearch = $derived.by(() => {
    if (search) lastSearch = search;
    return lastSearch;
  });
  const rowHasContent = $derived(!!tail || (barSearch?.rail.prompts.length ?? 0) > 0);
  $effect(() => {
    const hosted = search;
    if (!hosted) return;
    hosted.headerHosted = true;
    return () => { hosted.headerHosted = false; };
  });

  const dotColor = $derived(
    hue === 'green'
      ? 'var(--oc-green-bright)'
      : hue === 'yellow'
        ? 'var(--oc-yellow-bright)'
        : hue === 'blue'
          ? 'var(--oc-cyan)'
          : hue === 'red'
            ? 'var(--oc-coral)'
            : 'var(--oc-text-dim)',
  );
</script>

{#snippet toolsContent()}
  <span class="oc-tl-controls">
    
    <LayoutCellMarks {sessionId} />
    <TerminalUtilities {slot} {sessionId} {controller} width={width - toggleWidthFor(sessionId)} showsConnection={!tabPane} {agentFamily}
      groupSlot={frameHeader?.gridSlot ?? null} />
  </span>
{/snippet}

{#snippet widgetTools()}
  <span class="oc-tl-controls">
    <TerminalUtilities {slot} {sessionId} {controller} {width} showsConnection={false} {agentFamily} inHeader />
  </span>
{/snippet}

{#snippet headerContent()}
<div class="oc-tl-head" class:oc-tl-head-tabbed={!!tabPane} class:oc-tl-head-bare={!framed} data-terminal-header={sessionId} onfocusin={() => inputFocus.claim(slot)}>
  {#if tabPane}
    <div class="oc-tl-promptrow">
    
    {#if search && barSearch}
      <PromptHeader rail={barSearch.rail} inline onfocusterm={() => barSearch.focusTerminal()} />
    {/if}
    {#if tail}
      <span class="oc-tl-tail">{@render tail()}</span>
    {/if}
    </div>
  {:else}
    
    {#if showsStatusLight(agentFamily)}
    <span
      class="oc-tl-dot"
      class:oc-tl-dot-hollow={hue === 'grey' && !measured}
      style={`--oc-dot-color:${dotColor}`}
    ></span>
    {/if}
    <h2 class="oc-tl-name">{name}</h2>
    {#if statusWord && showsStatusLight(agentFamily)}
      {#if showsStatusWord}
        <span class="oc-tl-status">{statusWord}</span>
      {:else}
        <span class="oc-visually-hidden">{statusWord}</span>
      {/if}
    {/if}
    {@render toolsContent()}
    {#if tail}
      <span class="oc-tl-tail">{@render tail()}</span>
    {/if}
  {/if}
</div>
{/snippet}

{#if widgetForm}
  {#if showsHead}
    
    <div class="oc-tl-head oc-tl-head-bare oc-tl-widgetrow" data-terminal-header={sessionId} onfocusin={() => inputFocus.claim(slot)}>
      {#if search && barSearch}
        <PromptHeader rail={barSearch.rail} inline onfocusterm={() => barSearch.focusTerminal()} />
      {/if}
      {#if !toolsUp.up}{@render toolsContent()}{/if}
    </div>
  {/if}
{:else if !framed && showsHead}{@render headerContent()}{/if}

{#if tabPane}<div class="oc-tl-gap" aria-hidden="true"></div>{/if}

<style>
  @layer components {
    .oc-tl-head {
      display: flex;
      align-items: center;
      gap: 7px;
      padding: 0;
      flex: 1;
      container-type: inline-size;
      container-name: terminal-header;
      min-width: 0;
    }

    .oc-tl-head-bare {
      padding-inline: var(--oc-space-3);
    }

    .oc-tl-head-tabbed {
      align-self: stretch;
      flex-direction: column;
      align-items: stretch;
      padding-block: var(--oc-space-1) var(--oc-space-1);
      gap: var(--oc-space-1);
    }

    .oc-tl-promptrow {
      display: flex;
      align-items: center;
      gap: 7px;
      flex: 1 1 0;
      min-height: 0;
      min-width: 0;
    }

    :global(.oc-frame-title:has(> .oc-tl-head-tabbed)) {
      box-shadow: none;
    }

    .oc-tl-widgetrow {
      flex: none;
      padding-block: var(--oc-space-1);
    }

    :global(.oc-tl-widgetrow:not(:has(.prompt-header-root:not([hidden]), .cell-tools))) {
      display: none;
    }

    .oc-tl-gap {
      flex: 0 0 5px;
      height: 5px;
    }

    .oc-tl-controls {
      display: flex;
      align-items: center;
      gap: 5px;
      margin-left: auto;
      flex: 0 0 auto;
    }

    :global(.oc-frame-strip) .oc-tl-controls {
      gap: calc(var(--oc-space-1) / 2);
    }

    .oc-tl-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      flex: 0 0 auto;
      background: var(--oc-dot-color);
    }

    .oc-tl-dot-hollow {
      background: transparent;
      box-shadow: inset 0 0 0 1.5px var(--oc-dot-color);
    }

    .oc-tl-name {
      margin: 0;
      font-family: inherit;
      font-weight: 400;
      flex: 1 1 auto;
      font-size: var(--oc-fs-label);
      color: var(--oc-orange);
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      min-width: 0;
    }

    .oc-tl-status {
      font-size: var(--oc-fs-label);
      color: var(--oc-text-dim);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      max-width: 22%;
      flex: 0 1 auto;
    }

    @container (max-width: 480px) {
      .oc-tl-status { display: none; }
    }

    .oc-tl-tail {
      margin-left: auto;
      flex: 0 0 auto;
      display: flex;
      align-items: center;
      gap: 7px;
    }

    .oc-visually-hidden {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip-path: inset(50%);
      white-space: nowrap;
    }
  }
</style>
