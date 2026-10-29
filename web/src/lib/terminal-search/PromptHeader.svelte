
<script lang="ts">
    import { untrack } from 'svelte';

    import { t } from '../i18n/index.svelte';
    import { hasTypedBreak, isCutOff, watchBox } from './prompt-header-fit';
    import PromptHeaderControls from './PromptHeaderControls.svelte';
    import type { RailModel } from './rail-model.svelte';

    interface Props {
        rail: RailModel;
        onfocusterm?: () => void;
        inline?: boolean;
    }

    let { rail, onfocusterm, inline = false }: Props = $props();

    let expanded = $state(false);
    let overflows = $state(false);
    let root = $state<HTMLElement | null>(null);
    let barEl = $state<HTMLElement | null>(null);
    let previewEl = $state<HTMLElement | null>(null);

    let prompt = $derived(rail.headerPrompt);



    let hasPrev = $derived(rail.headerControls.hasPrev);
    let hasNext = $derived(rail.headerControls.hasNext);

    let fullText = $state<string | null>(null);

    let shown = $derived(expanded ? (fullText ?? prompt?.full ?? '') : (prompt?.text ?? ''));


    let promptKey = $derived(prompt ? `${prompt.ordinal}\u0000${prompt.text}` : '');

    let collapsedFor = '';

    $effect(() => {
        untrack(() => rail.retain());
        return () => rail.release();
    });

    $effect(() => {
        const key = promptKey;
        untrack(() => {
            if (key === collapsedFor) return;
            collapsedFor = key;
            expanded = false;
        });
    });

    $effect(() => {
        if (!expanded) {
            fullText = null;
            return;
        }
        const key = untrack(() => promptKey);
        const ordinal = untrack(() => prompt?.ordinal ?? 0);
        void rail.fullTextOf(ordinal).then((text) => {
            if (text !== null && untrack(() => expanded && promptKey === key)) fullText = text;
        });
    });

    const measure = (): void => { remeasure(); };
    $effect(() => {
        void promptKey;
        void previewEl;
        void expanded;
        untrack(measure);
    });

    $effect(() => watchBox(barEl, measure));

    $effect(() => {
        if (!expanded) return;
        const doc = root?.ownerDocument;
        if (!doc) return;
        const onDown = (event: MouseEvent): void => {
            if (root?.contains(event.target as Node | null)) return;
            close();
        };
        doc.addEventListener('mousedown', onDown);
        return () => doc.removeEventListener('mousedown', onDown);
    });

    $effect(() => {
        if (!expanded || !previewEl) return;
        try {
            previewEl.focus({ preventScroll: true });
        } catch (err) {
            console.warn('PromptHeader: could not focus the prompt', err);
        }
    });

    function remeasure(): void {
        if (expanded) return;
        const next = isCutOff(previewEl) || hasTypedBreak(prompt?.full ?? '');
        if (next !== overflows) overflows = next;
    }

    function close(): void {
        if (!expanded) return;
        expanded = false;
        onfocusterm?.();
    }

    function jump(ordinal: number): void {
        expanded = false;
        rail.jumpTo(ordinal);
    }

    function keepFocusInPane(event: MouseEvent): void {
        event.preventDefault();
    }

    function onPreviewKey(event: KeyboardEvent): void {
        if (!expanded || event.key !== 'Escape') return;
        event.preventDefault();
        event.stopPropagation();
        close();
    }
</script>


<div
    bind:this={root}
    class="prompt-header-root"
    class:prompt-header-root--inline={inline}
    hidden={prompt === null}
    role="presentation"
>
    <div
        bind:this={barEl}
        class="prompt-header"
        class:prompt-header--expanded={expanded}
        aria-label={t('prompt_header.label')}
        role="region"
    >
        
        <button data-base-exempt="the prompt bar header preview: a one-line label that is the key, beside the terminal prompt"
            bind:this={previewEl}
            type="button"
            class="prompt-header__preview"
            class:prompt-header__preview--expanded={expanded}
            onmousedown={keepFocusInPane}
            onkeydown={onPreviewKey}
            onclick={() => prompt && jump(prompt.ordinal)}>{shown}</button
        >
        <PromptHeaderControls
            {hasPrev}
            {hasNext}
            {overflows}
            {expanded}
            onpress={keepFocusInPane}
            onprev={() => prompt && jump(prompt.ordinal - 1)}
            onnext={() => prompt && jump(prompt.ordinal + 1)}
            ontoggle={() => (expanded = !expanded)}
        />
    </div>
</div>

<style>
  @layer components {
      .prompt-header-root {
          position: absolute;
          top: 0;
          right: 0;
          bottom: 0;
          left: 0;
          z-index: 30;
          display: flex;
          flex-direction: column;
          align-items: stretch;
          pointer-events: none;
      }

      .prompt-header-root[hidden] {
          display: none !important;
      }

      /* accent band plus a */
      .prompt-header {
          display: flex;
          flex: 0 0 auto;
          align-items: center;
          gap: var(--oc-space-1);
          padding: 2px 6px;
          border-bottom: 1px solid var(--oc-strip-edge);
          background: var(--oc-ground-card);
          box-shadow: inset 0 -5px 9px -5px var(--oc-strip-glow);
          color: var(--oc-text-secondary);
          font-family: var(--font-mono);
          font-size: var(--oc-fs-label);
          line-height: 1.5;
          pointer-events: auto;
          box-sizing: border-box;
      }

      .prompt-header__preview {
          flex: 1 1 auto;
          min-width: 0;
          height: 22px;
          padding: 0 var(--oc-space-1);
          border: none;
          border-radius: var(--oc-radius-sm);
          background: transparent;
          color: var(--oc-text-secondary);
          font-family: inherit;
          font-size: inherit;
          text-align: left;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          cursor: pointer;
      }

      .prompt-header__preview:hover,
      .prompt-header__preview:focus-visible {
          background: var(--oc-ground-hover);
          color: var(--oc-orange);
          outline: none;
          transform: none;
      }

      .prompt-header--expanded {
          align-items: flex-start;
          max-height: 40%;
      }

      .prompt-header__preview--expanded {
          align-self: stretch;
          height: auto;
          min-height: 0;
          overflow-x: hidden;
          overflow-y: auto;
          white-space: pre-wrap;
          overflow-wrap: anywhere;
          text-overflow: clip;
      }

      .prompt-header-root--inline {
          position: relative;
          inset: auto;
          z-index: auto;
          flex: 1 1 auto;
          align-self: stretch;
          min-width: 0;
      }

      .prompt-header-root--inline > .prompt-header {
          flex: 1 1 auto;
          border: 1px solid var(--oc-strip-edge);
          background: var(--oc-ground-titlerow);
          box-shadow: none;
      }

      .prompt-header-root--inline > .prompt-header--expanded {
          position: absolute;
          top: 0;
          right: 0;
          left: 0;
          z-index: 30;
          max-height: 40vh;
      }

      @media (max-width: 768px) {
          .prompt-header {
              padding: 3px 6px;
              gap: 2px;
          }

          .prompt-header__preview {
              height: 28px;
          }
  }
  }
</style>
