<script lang="ts" module>
  export type WindowKind = 'session' | 'terminal' | 'browser';

  export interface WindowChoice {
    id: string;
    label: string;
    why: string;
  }
</script>

<script lang="ts">
  import Button from '../../lib/base/Button.svelte';
  import Icon from '../ui/Icon.svelte';
  import { t } from '../../lib/i18n/index.svelte';

  let {
    kinds,
    open,
    choices,
    aimed = false,
    refusal = '',
    onheaddown,
    onhead,
    onchoicedown,
    onchoice,
  }: {
    kinds: readonly WindowKind[];
    open: WindowKind | null;
    choices: (kind: WindowKind) => WindowChoice[];
    aimed?: boolean;
    refusal?: string;
    onheaddown: (event: PointerEvent, kind: WindowKind) => void;
    onhead: (kind: WindowKind) => void;
    onchoicedown: (event: PointerEvent, kind: WindowKind, choice: WindowChoice) => void;
    onchoice: (kind: WindowKind, choice: WindowChoice) => void;
  } = $props();

  const ICONS: Readonly<Record<WindowKind, string>> = { session: 'bot', terminal: 'terminal', browser: 'globe' };
</script>

<div class="le-windows" data-window-picker role="group" aria-label={t('layout_editor.drawer.window_label')}>
  {#each kinds as kind (kind)}
    {@const list = choices(kind)}
    {@const isOpen = open === kind}
    {@const word = t(`layout_editor.drawer.${kind}`)}
    <div class="le-wfold" class:le-wfold--open={isOpen} data-window-fold={kind}>
      <Button
        variant="row"
        data-le-card=""
        data-picker-entry={kind}
        aria-expanded={isOpen}
        aria-controls={`le-wfold-${kind}`}
        aria-label={t('layout_editor.drawer.window_add', { kind: word })}
        title={t('layout_editor.drawer.window_add', { kind: word })}
        onpointerdown={(event) => onheaddown(event, kind)}
        onclick={() => onhead(kind)}
      >
        <span class="le-wfold__well" aria-hidden="true"><Icon name={ICONS[kind]} size={14} /></span>
        <span class="le-card__text">
          <span class="le-card__name">{word}</span>
          <span class="le-card__meta">{t(list.length === 1 ? 'layout_editor.drawer.window_count_one' : 'layout_editor.drawer.window_count', { count: list.length })}</span>
        </span>
        <span class="le-wfold__chev" aria-hidden="true"></span>
      </Button>
      {#if isOpen}
        <div class="le-wfold__body" id={`le-wfold-${kind}`}>
          {#if list.length > 0}<p class="le-wfold__hint">{t(aimed ? 'layout_editor.drawer.window_aimed' : 'layout_editor.drawer.window_hint')}</p>{/if}
          <ul class="le-wfold__list" aria-label={word}>
            {#each list as choice (choice.id)}
              <li>
                <Button
                  variant="row"
                  data-le-card=""
                  data-placed={choice.why !== '' ? '' : undefined}
                  data-picker-row={choice.id}
                  aria-disabled={choice.why !== ''}
                  title={choice.why || choice.label}
                  onpointerdown={(event) => onchoicedown(event, kind, choice)}
                  onclick={() => onchoice(kind, choice)}
                >
                  <span class="le-wfold__dot" aria-hidden="true"></span>
                  <span class="le-card__text">
                    <span class="le-card__name">{choice.label}</span>
                    {#if choice.why}<span class="le-card__meta">{choice.why}</span>{/if}
                  </span>
                </Button>
              </li>
            {:else}
              <li class="le-wfold__none" role="status">{t('layout_editor.drawer.window_none', { kind: word })}</li>
            {/each}
          </ul>
          {#if refusal}<p class="le-wfold__hint le-wfold__refusal" role="status">{refusal}</p>{/if}
        </div>
      {/if}
    </div>
  {/each}
  <hr class="le-windows__rule" />
</div>

<style>
  @layer components {
    .le-windows {
      display: flex;
      flex-direction: column;
      gap: 2px;
      min-width: 0;
    }

    .le-windows__rule {
      height: 0;
      margin: var(--oc-space-1) 0 var(--oc-space-2);
      border: 0;
      border-top: 1px solid var(--oc-line-rule);
    }

    .le-windows :global([data-picker-entry]) {
      min-height: 34px;
      padding: var(--oc-space-1) 6px;
      gap: var(--oc-space-2);
    }

    .le-wfold--open :global([data-picker-entry]) {
      background: var(--oc-ground-hover);
      border-color: var(--oc-line-rule);
    }

    .le-wfold__well {
      display: inline-flex;
      flex: none;
      align-items: center;
      justify-content: center;
      width: 32px;
      height: 24px;
      background: var(--oc-ground-raised);
      border: var(--oc-border, 1px) solid var(--oc-line-faint);
      border-radius: var(--oc-radius-sm, 2px);
      color: var(--oc-text-secondary);
    }

    .le-wfold__chev {
      flex-shrink: 0;
      width: 7px;
      height: 7px;
      margin: 0 var(--oc-space-1) 0 auto;
      border-right: 1px solid var(--oc-text-muted);
      border-bottom: 1px solid var(--oc-text-muted);
      transform: rotate(-45deg);
      transition: transform var(--oc-motion-fast, 120ms) ease;
    }

    .le-wfold--open .le-wfold__chev {
      transform: rotate(45deg);
    }

    .le-wfold__body {
      display: flex;
      flex-direction: column;
      gap: 2px;
      margin: 2px 0 var(--oc-space-1) 22px;
      padding: 2px 0 2px var(--oc-space-2);
      box-shadow: inset 1px 0 0 var(--oc-line-rule);
    }

    .le-wfold__hint {
      margin: 0;
      padding: 2px 6px;
      font-size: var(--oc-fs-label);
      color: var(--oc-text-muted);
    }

    .le-wfold__refusal {
      color: var(--oc-text-secondary);
    }

    .le-wfold__list {
      margin: 0;
      padding: 0;
      list-style: none;
    }

    .le-windows :global([data-picker-row]) {
      min-height: 26px;
      padding: 3px 6px;
      gap: var(--oc-space-2);
    }

    .le-wfold__dot {
      flex: none;
      width: 5px;
      height: 5px;
      background: var(--oc-green);
    }

    .le-wfold__none {
      padding: var(--oc-space-1) 6px;
      font-size: var(--oc-fs-label);
      color: var(--oc-text-muted);
    }
  }
</style>
