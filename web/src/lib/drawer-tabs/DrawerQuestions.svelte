<script lang="ts">
  import { motionReduced } from '../motion/motion';
  import '../ledger/ledger-chrome.css';
  import { slide } from 'svelte/transition';
  import { t } from '../i18n/index.svelte';
  import { sessions } from '../../opscenter/api';
  import ApprovalCard from '../approvals/ApprovalCard.svelte';
  import { approvals } from '../approvals/approvals.svelte';
  import { createdMs, oldestFirst, type ApprovalItem } from '../approvals/approvals-model';
  import { jumpToApproval } from '../approvals/mount-approvals.svelte';
  import { activeFlyout, closeFlyout } from '../sidebar-widgets/flyout.svelte';

  type ThemesGlobal = { Themes?: { applyScopeTo?(el: HTMLElement, ctx: { pinnedTheme: string | null }): () => void } };

  const items = $derived(oldestFirst(approvals.items));
  const reduced = motionReduced();
  const ms = reduced ? 0 : 200;
  let now = $state(Date.now());
  let list = $state<HTMLElement | null>(null);

  $effect(() => {
    const timer = setInterval(() => (now = Date.now()), 15_000);
    return () => clearInterval(timer);
  });

  function pinFor(item: ApprovalItem): string | null {
    const rows = sessions.data ?? [];
    const id = item.session_id;
    const row = rows.find((r) => r.session?.id === id)
      ?? (item.tmux_session ? rows.find((r) => r.tmux_session === item.tmux_session) : undefined);
    return row?.pinned_theme ?? null;
  }

  function themed(el: HTMLElement, pin: string | null) {
    const apply = (p: string | null) => (globalThis as ThemesGlobal).Themes?.applyScopeTo?.(el, { pinnedTheme: p }) ?? (() => {});
    let release = apply(pin);
    return {
      update(next: string | null) {
        release();
        release = apply(next);
      },
      destroy: () => release(),
    };
  }

  function age(item: ApprovalItem): string {
    const at = createdMs(item);
    if (at === null) return '';
    const s = Math.max(0, Math.round((now - at) / 1000));
    if (s < 60) return t('drawer.questions.age_s', { n: s });
    if (s < 3600) return t('drawer.questions.age_m', { n: Math.floor(s / 60) });
    return t('drawer.questions.age_h', { n: Math.floor(s / 3600) });
  }

  function cells(): HTMLElement[] {
    return list ? [...list.querySelectorAll<HTMLElement>('[data-dq-cell]')] : [];
  }

  function leave(): void {
    const was = activeFlyout();
    if (closeFlyout()) document.querySelector<HTMLElement>(`[data-rail-widget="${was}"]`)?.focus();
  }

  function onKeydown(event: KeyboardEvent): void {
    const cell = (event.target as HTMLElement | null)?.closest<HTMLElement>('[data-dq-cell]');
    if (!cell || event.altKey || event.ctrlKey || event.metaKey) return;
    const onCell = event.target === cell;
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      if (onCell) leave();
      else cell.focus();
      return;
    }
    if (!onCell) return;
    const toggle = cell.querySelector<HTMLElement>('[data-qc-toggle]');
    if ((event.key === 'Enter' || event.key === ' ') && toggle?.getAttribute('aria-expanded') === 'false') {
      event.preventDefault();
      toggle.click();
      return;
    }
    const all = cells();
    const at = all.indexOf(cell);
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      all[Math.max(0, Math.min(all.length - 1, at + (event.key === 'ArrowDown' ? 1 : -1)))]?.focus();
    } else if (cell.dataset.dqSource === 'dialog' && /^[1-9]$/.test(event.key)) {
      const picks = cell.querySelectorAll<HTMLElement>('.ap-actions > .oc-check, .ap-actions > [data-ap-option]');
      if (picks[Number(event.key) - 1]) {
        event.preventDefault();
        picks[Number(event.key) - 1]?.click();
      }
    } else if (event.key === 'Enter' && cell.dataset.dqSource === 'dialog') {
      const submit = cell.querySelector<HTMLElement>('[data-ap-bar] > [data-ap-submit]');
      if (submit) {
        event.preventDefault();
        submit.click();
      }
    }
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<ul class="dq-list" bind:this={list} aria-label={t('drawer.questions.list')} data-drawer-questions onkeydown={onKeydown}>
  {#each items as item (item.id)}
    <li
      class="dq-cell pledger"
      data-dq-cell={item.id}
      data-dq-source={item.source}
      tabindex="0"
      use:themed={pinFor(item)}
      in:slide={{ duration: ms }}
      out:slide={{ duration: ms }}
    >
      <ApprovalCard {item} onJump={jumpToApproval} foldable age={age(item)} />
    </li>
  {/each}
</ul>

<style>
  @layer components {
    .dq-list {
      list-style: none;
      margin: 0;
      padding: var(--oc-space-2);
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-2);
      overflow-anchor: none;
      font-family: var(--font-mono);
    }

    .dq-cell {
      --_bd: color-mix(in oklab, var(--oc-orange) 75%, var(--oc-line-rule));
      display: flex;
      flex-direction: column;
      min-width: 0;
      border: var(--oc-border, 1px) solid var(--_bd);
      border-radius: var(--oc-radius-sm, 2px);
      background: var(--oc-ground-card);
      color: var(--oc-text-primary);
      outline: none;
    }

    .dq-cell :global(.ap-card) {
      box-shadow: none;
    }

    .dq-cell[data-dq-source='dialog'] :global(.ap-actions) {
      counter-reset: dq-opt;
    }

    .dq-cell[data-dq-source='dialog'] :global(.ap-actions > [data-ap-option]::before),
    .dq-cell[data-dq-source='dialog'] :global(.ap-actions > .oc-check .oc-check__label::before) {
      counter-increment: dq-opt;
      content: counter(dq-opt);
      margin-right: var(--oc-space-1);
      color: var(--oc-orange);
      opacity: 0.8;
    }

    @media (hover: none) {
      .dq-cell :global(.ap-actions > [data-ap-option]::before),
      .dq-cell :global(.ap-actions > .oc-check .oc-check__label::before) {
        content: none;
      }
    }

    @media (max-width: 1023px) {
      .dq-cell :global(.ap-card .modal-btn),
      .dq-cell :global(.ap-input),
      .dq-cell :global(.oc-check),
      .dq-cell :global(.qc-toggle) {
        min-height: 44px;
      }

      .dq-cell :global(.ap-bar .modal-btn) {
        height: 44px;
      }

      .dq-cell :global(.ap-bar .ap-jump) {
        width: 44px;
      }
    }
  }
</style>
