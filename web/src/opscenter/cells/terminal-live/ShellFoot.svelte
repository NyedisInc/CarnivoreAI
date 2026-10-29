<script lang="ts">
  import { paneFacts, releasePaneFacts, type Resource, type SessionPaneFacts } from '../../api';
  import { t } from '../../../lib/i18n/index.svelte';

  let { sessionId, width = 0 }: { sessionId: string; width?: number } = $props();

  const SHOW_COMMAND_MIN = 360;
  const SHOW_SIZE_MIN = 480;

  let factsResource = $state<Resource<SessionPaneFacts> | null>(null);

  $effect(() => {
    const id = sessionId;
    if (!id) {
      factsResource = null;
      return;
    }
    factsResource = paneFacts(id);
    return () => releasePaneFacts(id);
  });

  const facts = $derived(factsResource?.data ?? null);
  const roomy = (min: number): boolean => width <= 0 || width >= min;
  const size = $derived(
    facts?.cols && facts?.rows ? t('usage.foot.shell.size_value', { cols: facts.cols, rows: facts.rows }) : '',
  );
</script>

<div class="oc-tf" role="group" aria-label={t('usage.foot.shell.region')} data-shell-foot="">
  {#if facts?.cwd_display}
    <span class="oc-sf-cwd" data-field="cwd">
      <span class="oc-sf-cwd-text"><bdi>{facts.cwd_display}</bdi></span>
    </span>
  {/if}
  {#if facts?.command && roomy(SHOW_COMMAND_MIN)}
    <span class="oc-sf-field" data-field="command">
      <span class="oc-tf-label">{t('usage.foot.shell.command')}</span>
      <span class="oc-tf-num">{facts.command}</span>
    </span>
  {/if}
  {#if size && roomy(SHOW_SIZE_MIN)}
    <span class="oc-sf-field" data-field="size">
      <span class="oc-tf-label">{t('usage.foot.shell.size')}</span>
      <span class="oc-tf-num">{size}</span>
    </span>
  {/if}
</div>

<style>
  @layer components {
    .oc-tf {
      display: flex;
      align-items: center;
      flex-wrap: nowrap;
      gap: 10px;
      padding: 3px var(--oc-space-3);
      min-height: 1.5em;
      background: var(--oc-ground-titlerow);
      border-top: 1px solid var(--oc-line-rule);
      font-size: var(--oc-fs-label);
      color: var(--oc-text-secondary);
      overflow: hidden;
      flex: 0 0 auto;
      box-sizing: border-box;
    }

    .oc-tf > span:not(:first-child) {
      position: relative;
      padding-left: 14px;
    }

    .oc-tf > span:not(:first-child)::before {
      content: '';
      position: absolute;
      left: 3px;
      top: 50%;
      transform: translateY(-50%);
      width: 1px;
      height: 11px;
      background: var(--oc-line-rule);
    }

    .oc-sf-cwd {
      flex: 1 1 0;
      min-width: 0;
      display: flex;
    }

    .oc-sf-cwd-text {
      min-width: 0;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      direction: rtl;
      text-align: left;
      color: var(--oc-text-secondary);
    }

    .oc-sf-field {
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-1);
      flex: 0 1 auto;
      min-width: 0;
    }

    .oc-tf-label {
      color: var(--oc-text-dim);
      white-space: nowrap;
      flex: 0 0 auto;
    }

    .oc-tf-num {
      color: var(--oc-text-secondary);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      min-width: 0;
    }
  }
</style>
