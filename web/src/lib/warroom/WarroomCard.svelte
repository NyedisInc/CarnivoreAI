<script lang="ts">
  import { truncatedTip } from '../tooltip/truncated-tip';
  import StatusLed from '../StatusLed.svelte';
  import SessionFace from '../sessions/SessionFace.svelte';

  interface Props {
    kind: 'asleep' | 'browser' | 'offline' | 'remote';
    name: string;
    lines: readonly string[];
    unread?: boolean;
    onopen: () => void;
    dim?: boolean;
  }
  let { kind, name, lines, unread = false, onopen, dim = false }: Props = $props();

  function onkeydown(event: KeyboardEvent): void {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    onopen();
  }
</script>

<div class="ww-tile ww-card" class:ww-dim={dim} data-wr-card={kind} role="button" tabindex="0" onclick={onopen} {onkeydown}>
  <div class="ww-bar">
    {#if kind === 'asleep'}<SessionFace row={{ unread }} lifecycle="asleep" size="9px" />{/if}
    {#if kind === 'offline'}<StatusLed status="dead" size="9px" />{/if}
    <span class="ww-name" use:truncatedTip={name}>{name}</span>
  </div>
  <div class="ww-card-body">
    {#each lines as line (line)}<span class="ww-card-line">{line}</span>{/each}
  </div>
</div>
