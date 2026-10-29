<script lang="ts">
  import type { Snippet } from 'svelte';
  import { t } from '../../../lib/i18n/index.svelte';
  import State from '../../../lib/base/State.svelte';
  import { titlelessHost } from '../../shell/frame-header.svelte';
  import type { WidgetHandle } from './define-widget.svelte';
  import { statusKey, type WidgetStatus } from './widget-status';

  type ControlsPlace = 'header' | 'body' | 'corner';

  let { widget, status = 'ready', note = '', controls, bare = false, children }: {
    widget: WidgetHandle;
    status?: WidgetStatus;
    note?: string;
    controls?: Snippet<[ControlsPlace]>;
    bare?: boolean;
    children?: Snippet;
  } = $props();

  const frame = $derived(widget.frame);
  const corner = titlelessHost();
  const inHeader = $derived(!!frame?.drawn && !!controls);

  $effect(() => {
    const host = frame;
    if (!host || !inHeader) return;
    host.action = up;
    return () => {
      if (host.action === up) host.action = null;
    };
  });
</script>

{#snippet up()}{@render controls?.('header')}{/snippet}

{#if bare}
  {@render children?.()}
{:else}
<div class="oc-wshell" data-oc-base data-widget={widget.definition.id} data-widget-status={status} data-widget-session={widget.sessionId || undefined}>
  {#if controls && !inHeader && !frame?.suppressed}
    <div class={corner ? 'oc-wshell-corner' : 'oc-wshell-bar'} data-widget-controls={corner ? 'corner' : 'body'}>
      {@render controls(corner ? 'corner' : 'body')}
    </div>
  {/if}
  {#if status === 'ready'}
    {@render children?.()}
  {:else}
    <State kind={status === 'loading' || status === 'error' ? status : 'empty'} inline data-widget-note={status} title={note || t(statusKey(status))} />
  {/if}
</div>
{/if}

<style>
  @layer components {
    .oc-wshell {
      position: relative;
      display: flex;
      flex-direction: column;
      height: 100%;
      min-height: 0;
      overflow: hidden;
    }

    .oc-wshell-bar {
      flex: 0 0 auto;
      padding: var(--oc-space-1) var(--oc-space-1) 0;
    }

    .oc-wshell-corner {
      display: contents;
    }
  }
</style>
