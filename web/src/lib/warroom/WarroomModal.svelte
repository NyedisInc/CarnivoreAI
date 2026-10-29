<!-- pop-out window -->
<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import TerminalLive from '../../opscenter/cells/terminal-live/Cell.svelte';
  import WidgetHead from '../../opscenter/shell/WidgetHead.svelte';
  import ModalShell from '../launchpad/ModalShell.svelte';
  import { WAR_ROOM_H, WAR_ROOM_W } from './modal-size';
  import ZoneShell from '../zone-shell/ZoneShell.svelte';
  import { createZone } from '../zone-shell/zone.svelte';
  import type { TabRef } from '../zone-shell/zone-types';
  import { metaFor } from '../../opscenter/engine/meta';
  import { slotForSession } from '../../opscenter/engine/slot-identity';
  import type { SlotId } from '../../opscenter/engine/types';
  import { sessions } from '../../opscenter/api';
  import { openSession } from '../../opscenter/api/host';
  import { openLayout } from '../../opscenter/layouts/page.svelte';
  import type { SessionInfo } from '../../opscenter/api/types';
  import { layouts } from '../layouts-bridge/api.svelte';
  import { t } from '../i18n/index.svelte';
  import { layoutChoice } from './go-to-layout';
  import CascadeMenu from '../drawer-tabs/CascadeMenu.svelte';
  import type { MenuNode } from '../drawer-tabs/add-component-menu';

  let { info, close, register }: {
    info: SessionInfo;
    close: (value: null) => void;
    register?: (close: () => void) => void;
  } = $props();

  const sessionId = untrack(() => info.session.id);
  const slot = slotForSession(sessionId, sessions.data) as SlotId;
  const meta = metaFor(slot);
  const zone = createZone({
    key: 'warroom',
    tabs: (): readonly TabRef[] => [{ key: slot, kind: 'widget' }],
    active: () => slot,
    select: () => {},
    panel: () => 'open',
    strip: 'none',
    toolbar: 'header',
    menuHost: 'popout',
    headerId: () => slot,
  });
  const header = zone.headerFor(slot);
  header.drawn = true;
  header.takesBars = false;

  const title = $derived((info.label ?? '').trim() || sessionId);
  const choice = $derived(layoutChoice(info.session_row_id, layouts.data ?? []));

  let bodyEl = $state<HTMLElement | null>(null);
  let bodyW = $state(0);
  let bodyH = $state(0);
  let picking = $state(false);
  let layoutButton = $state<HTMLButtonElement | null>(null);
  const layoutNodes = $derived<MenuNode[]>(choice.layouts.map((one): MenuNode => ({ id: `layout:${one.uuid}`, label: one.name, run: () => goLayout(one.uuid) })));

  function dismiss(): void {
    close(null);
  }

  function goSession(): void {
    dismiss();
    openSession(sessionId, info.tmux_session);
  }

  function goLayout(uuid: string): void {
    picking = false;
    dismiss();
    void openLayout(uuid, false, choice.sessionUuid);
  }

  function onLayoutButton(): void {
    if (choice.kind === 'one') goLayout(choice.layouts[0]!.uuid);
    else if (choice.kind === 'many') picking = !picking;
  }

  function escapeCloses(event: KeyboardEvent): boolean {
    if (picking) {
      picking = false;
      return false;
    }
    return !(event.target instanceof Element && event.target.closest('.oc-tl-body') !== null);
  }

  onMount(() => {
    register?.(dismiss);
    void layouts.refresh(true);
    const focusTerminal = (): boolean => {
      const input = bodyEl?.querySelector<HTMLTextAreaElement>('.oc-tl-body textarea');
      input?.focus();
      return !!input;
    };
    if (focusTerminal() || !bodyEl) return;
    const watch = new MutationObserver(() => {
      if (focusTerminal()) watch.disconnect();
    });
    watch.observe(bodyEl, { childList: true, subtree: true });
    return () => watch.disconnect();
  });
</script>

{#snippet goButtons()}
  <span class="wrm-go">
    <button type="button" class="oc-btn oc-btn--tool" data-warroom-go="session" onclick={goSession}>{t('warroom.modal.go_session')}</button>
    <span class="wrm-go-layout">
      <button type="button" class="oc-btn oc-btn--tool" data-warroom-go="layout" bind:this={layoutButton} disabled={choice.kind === 'none'}
        title={choice.kind === 'none' ? t('warroom.modal.no_layout') : ''}
        aria-haspopup={choice.kind === 'many' ? 'menu' : undefined} aria-expanded={choice.kind === 'many' ? picking : undefined}
        onclick={onLayoutButton}>{t('warroom.modal.go_layout')}</button>
      {#if picking && choice.kind === 'many'}
        <CascadeMenu root={layoutNodes} anchor={layoutButton} label={t('warroom.modal.pick_layout')} onClose={() => (picking = false)} />
      {/if}
    </span>
  </span>
{/snippet}

{#snippet head()}
  <div class="wrm-head">
    <WidgetHead {meta} {header} {title} corner={goButtons} onClose={dismiss} withRight={false} />
  </div>
{/snippet}

{#snippet terminal()}
  <TerminalLive width={bodyW} height={bodyH} {meta} instance={slot} />
{/snippet}

<ModalShell
  title={t('warroom.modal.label', { name: title })}
  onCancel={dismiss}
  overlayClass="text-prompt-modal"
  width={WAR_ROOM_W}
  height={WAR_ROOM_H}
  fill
  {head}
  trapFocus={false}
  escapeGuard={escapeCloses}
  data-warroom-modal
>
  <div class="wrm-body" bind:this={bodyEl} bind:clientWidth={bodyW} bind:clientHeight={bodyH}>
    <ZoneShell {zone} tab={terminal} bare />
  </div>
</ModalShell>

<style>
  @layer components {
    .wrm-head {
      flex: none;
    }

    .wrm-body {
      flex: 1 1 auto;
      min-height: 0;
      min-width: 0;
      background: var(--oc-ground-panel);
    }

    .wrm-go {
      display: inline-flex;
      align-items: center;
      gap: var(--oc-space-2);
    }

    .wrm-go-layout {
      position: relative;
      display: inline-flex;
    }
  }
</style>
