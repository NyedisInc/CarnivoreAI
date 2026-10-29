<script lang="ts">
  import { t } from '../sdk';
  import { Icon } from '../sdk/ui';
  import { copyToClipboard } from './task-manager-copy';

  let { text, copyText = undefined, lang = '' }: { text: string; copyText?: string; lang?: string } = $props();

  const COPIED_MS = 1600;
  let copied = $state(false);
  let code = $state<HTMLElement | null>(null);
  let timer: ReturnType<typeof setTimeout> | undefined;

  function copy(): void {
    clearTimeout(timer);
    void copyToClipboard(copyText ?? text).then((ok) => {
      if (ok) {
        copied = true;
        timer = setTimeout(() => (copied = false), COPIED_MS);
        return;
      }
      copied = false;
      if (!code) return;
      const range = document.createRange();
      range.selectNodeContents(code);
      const selection = window.getSelection();
      selection?.removeAllRanges();
      selection?.addRange(range);
    });
  }

  $effect(() => () => clearTimeout(timer));
  const label = $derived(copied ? t('cplug.huddle.command.copied') : t('cplug.huddle.command.copy'));
</script>

<div class="hcb" data-task-manager-command>
  {#if lang}<span class="hcb-lang" data-task-manager-command-lang>{lang}</span>{/if}
  <pre class="hmd-pre hcb-pre"><code bind:this={code}>{text}</code></pre>
  <button type="button" class="hcb-copy" class:hcb-copy--done={copied} title={label} aria-label={label} data-task-manager-copy onclick={copy}>
    <Icon name={copied ? 'check' : 'copy'} size={14} />
  </button>
  <span class="hcb-live" role="status" aria-live="polite">{copied ? label : ''}</span>
</div>

<style>
  @layer components {
    .hcb {
      position: relative;
      min-width: 0;
    }

    .hcb-pre {
      margin: 0;
      padding: var(--oc-space-2) 2.5rem var(--oc-space-2) var(--oc-space-2);
      overflow-x: auto;
      border: var(--oc-border) solid var(--oc-line-faint);
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-hover);
      font-family: var(--font-mono);
      font-size: 0.92em;
      white-space: pre;
    }

    .hcb-lang {
      position: absolute;
      right: 2.5rem;
      top: 0;
      padding: 0 var(--oc-space-1);
      color: var(--oc-text-secondary);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
      letter-spacing: var(--oc-tracking-label, 0.1em);
      text-transform: uppercase;
      pointer-events: none;
    }

    .hcb-copy {
      position: absolute;
      top: 0;
      right: 0;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 2.25rem;
      height: 2.25rem;
      padding: 0;
      border: var(--oc-border) solid transparent;
      border-radius: var(--oc-radius-sm);
      background: transparent;
      color: var(--oc-text-secondary);
      cursor: pointer;
    }

    .hcb-copy:hover {
      background: var(--oc-ground-field);
      color: var(--oc-text-primary);
    }

    .hcb-copy--done {
      color: var(--oc-green);
    }

    .hcb-live {
      position: absolute;
      width: 0.0625rem;
      height: 0.0625rem;
      overflow: hidden;
      clip-path: inset(50%);
    }
  }
</style>
