<script lang="ts">
  import { activeTerminalSessionId } from '../../lib/active-terminal';
  import { sessionGit, releaseSessionGit } from '../../api/session-git.svelte';
  import type { Resource } from '../../api/poll.svelte';
  import type { SessionGitStatus } from '../../api/types';
  import WidgetIcon from '../../ui/WidgetIcon.svelte';
  import { fk } from './labels';
  import { glanceOf, glanceWords } from './glance-facts';
  import { watchOnScreen } from './on-screen';

  let { onopen }: { data?: unknown; onopen: () => void } = $props();

  const ICON_PX = 12;
  let root = $state<HTMLButtonElement | null>(null);
  let onScreen = $state(false);
  $effect(() => (root ? watchOnScreen(root, (yes) => (onScreen = yes)) : undefined));

  const sessionId = $derived(activeTerminalSessionId());
  let held = $state.raw<Resource<SessionGitStatus> | null>(null);
  $effect(() => {
    const id = sessionId;
    if (!id || !onScreen) return;
    const mine = sessionGit(id);
    held = mine;
    return () => {
      releaseSessionGit(id);
      if (held === mine) held = null;
    };
  });

  const words = $derived(glanceWords(glanceOf(held?.data ?? null)));
  const phrase = $derived(fk(words.key, words.vars));
  const whole = $derived(fk('glance.title', { phrase }));
</script>

<button type="button" class="fgl" bind:this={root} data-files-glance data-glance-kind={words.key} title={whole} aria-label={whole} onclick={onopen}>
  <WidgetIcon name="folder" widget="core.files" size={ICON_PX} />
  <span class="fgl-phrase">{phrase}</span>
</button>

<style>
  @layer components {
    .fgl {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-1);
      align-items: center;
      justify-content: center;
      box-sizing: border-box;
      width: 100%;
      height: 100%;
      min-width: 0;
      padding: 0;
      border: var(--oc-border) solid var(--oc-line-panel);
      border-radius: var(--oc-radius-sm);
      background: var(--oc-ground-field);
      color: var(--oc-cyan);
      font: inherit;
      cursor: pointer;
      overflow: hidden;
    }

    .fgl-phrase {
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-family: var(--font-mono);
      font-size: var(--oc-fs-micro);
      line-height: 1.2;
      color: var(--oc-text-secondary);
    }
  }
</style>
