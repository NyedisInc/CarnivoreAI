<!--
  The Swarm agent drawer (#1363, slice A): a slide-out that grows from UNDER the left (Swarm) drawer toward the right, hosting ONE agent's chat, with a second tab, the Tasks
  Viewer, which is the huddle lists view filtered to that agent. It replaces opening the agent's full page on a click.

  ONE CHAT COMPONENT: the body is `cplugs/huddle/chat/ChatWidget.svelte` (the same one the agent page and the widget
  mount); this file only frames it, so a pop-out window or a widget host mounts the same component. The Tasks Viewer is
  `HuddleBody` with its `agent` prop, never a copy of the lists.

  Width: the left drawer's width by default, dragged on the right edge, remembered per device (`agent-drawer.svelte.ts`).
  The kebab menu pops it out into its own window or makes it a widget of the current layout (`agent-dock.ts`); the title row
  drags onto the layout to drop it as a widget. At 1024 px and wider the open drawer DOCKS: the terminal moves to its right
  instead of sitting under it (`dockBesideTerminal`, #1408). Close: the close key, Escape, or a press (pointerdown) outside it. COPIED, NOT INVENTED: the title strip and quiet tabs of `ChatWidget.svelte` and
  `web/src/lib/ledger/ledger-chrome.css` (fixed-height title-row ground, a hairline by box-shadow, a small tracked
  label in the accent).
-->
<script lang="ts">
    import { motionReduced } from '../motion/motion';
    import { onMount } from 'svelte';
    import { fly } from 'svelte/transition';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import { t as appT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import AgentChatFrame from '../../cplugs/huddle/agents/AgentChatFrame.svelte';
    import { openAgentTerminal } from '../../cplugs/huddle/agents/agent-terminal';
    import { addAgentWidget, beginAgentBarDrag, popOutAgent } from './agent-dock';
    import {
        AGENT_DRAWER_MAX_PX, AGENT_DRAWER_MIN_PX, agentDrawer, closeAgentDrawer, dockBesideTerminal, drawerAnchorLeft, drawerWidth, keepsDrawerOpen, resetDrawerWidth, setDrawerWidth, widthFromPointer,
    } from './agent-drawer.svelte';

    interface Props {
        t?: Translate;
    }

    const { t = appT }: Props = $props();

    const width = $derived(drawerWidth());
    let dragging = false;
    const slide = $derived({
        x: -width,
        duration: typeof Element === 'undefined' || typeof Element.prototype.animate !== 'function' || motionReduced() ? 0 : 180,
    });
    let opener: HTMLElement | null = null;

    let panel: HTMLElement | null = $state(null);
    function popOut(): void {
        if (agentDrawer.id !== null && popOutAgent(agentDrawer.id, width)) closeAgentDrawer();
    }

    function makeWidget(): void {
        if (agentDrawer.id !== null && addAgentWidget(agentDrawer.id, null)) closeAgentDrawer();
    }

    async function agentTerminal(): Promise<void> {
        if (agentDrawer.id !== null && await openAgentTerminal(agentDrawer.id)) closeAgentDrawer();
    }

    const menu = $derived([
        { key: 'popout', label: t('cplug.huddle.swarm.drawer.pop_out'), run: popOut },
        { key: 'terminal', label: t('cplug.huddle.swarm.drawer.agent_terminal'), run: () => void agentTerminal() },
        { key: 'widget', label: t('cplug.huddle.swarm.drawer.make_widget'), run: makeWidget },
    ]);

    function barDown(event: PointerEvent): void {
        if (agentDrawer.id !== null) beginAgentBarDrag(event.currentTarget as HTMLElement, event, agentDrawer.id, panel, () => { closeAgentDrawer(); });
    }

    let returnFocus = false;

    function closeWithFocus(): void {
        returnFocus = true;
        closeAgentDrawer();
    }

    $effect(() => {
        if (agentDrawer.id !== null && opener === null && typeof document !== 'undefined') {
            opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        }
        if (agentDrawer.id === null && opener) {
            if (returnFocus && document.contains(opener)) opener.focus();
            opener = null;
        }
        if (agentDrawer.id === null) returnFocus = false;
    });

    $effect(() => {
        dockBesideTerminal(agentDrawer.id !== null, width);
    });

    onMount(() => {
        const redock = (): void => {
            dockBesideTerminal(agentDrawer.id !== null, drawerWidth());
        };
        window.addEventListener('resize', redock);
        const onKey = (event: KeyboardEvent): void => {
            if (event.key !== 'Escape' || agentDrawer.id === null || event.defaultPrevented) return;
            closeWithFocus();
        };
        const onDown = (event: PointerEvent): void => {
            if (agentDrawer.id === null || keepsDrawerOpen(event.target)) return;
                closeAgentDrawer();
        };
        window.addEventListener('keydown', onKey);
        document.addEventListener('pointerdown', onDown, true);
        return () => {
            window.removeEventListener('resize', redock);
            dockBesideTerminal(false, 0);
            window.removeEventListener('keydown', onKey);
            document.removeEventListener('pointerdown', onDown, true);
        };
    });

    function down(event: PointerEvent): void {
        if (event.button !== 0) return;
        dragging = true;
        try {
            (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId);
        } catch {
        }
        event.preventDefault();
    }

    function move(event: PointerEvent): void {
        if (dragging) setDrawerWidth(widthFromPointer(event.clientX, drawerAnchorLeft()), false);
    }

    function up(event: PointerEvent): void {
        if (!dragging) return;
        dragging = false;
        setDrawerWidth(widthFromPointer(event.clientX, drawerAnchorLeft()), true);
    }

    function key(event: KeyboardEvent): void {
        const step = 16;
        const next = event.key === 'ArrowRight' || event.key === 'ArrowUp' ? width + step
            : event.key === 'ArrowLeft' || event.key === 'ArrowDown' ? width - step
                : event.key === 'Home' ? AGENT_DRAWER_MIN_PX : event.key === 'End' ? AGENT_DRAWER_MAX_PX : null;
        if (next === null) return;
        event.preventDefault();
        setDrawerWidth(next, true);
    }
</script>

{#if agentDrawer.id !== null}
    <aside class="had" transition:fly={slide} bind:this={panel} style:width="min({width}px, 85vw)" aria-label={t('cplug.huddle.swarm.drawer.label')} data-agent-drawer={agentDrawer.id} data-agent-drawer-width={width}>
        <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
        <div class="had-grip" role="separator" aria-orientation="vertical" tabindex="0" data-agent-drawer-grip
             aria-label={t('cplug.huddle.swarm.drawer.resize')} aria-valuemin={AGENT_DRAWER_MIN_PX} aria-valuemax={AGENT_DRAWER_MAX_PX} aria-valuenow={width}
             onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up} onkeydown={key} ondblclick={resetDrawerWidth}></div>
        <AgentChatFrame id={agentDrawer.id} bind:tab={agentDrawer.tab} {t} onOpenedTerminal={closeAgentDrawer} onBarDown={barDown} menu={menu}>
            {#snippet actions()}
                <button type="button" class="oc-ibtn oc-ibtn--bare had-close" data-agent-drawer-close aria-label={t('cplug.huddle.swarm.drawer.close')}
                        onclick={closeWithFocus}><Icon name="close" size={12} /></button>
            {/snippet}
        </AgentChatFrame>
    </aside>
{/if}

<style>
  @layer components {
    .had {
      position: fixed;
      top: env(safe-area-inset-top, 0px);
      left: 0;
      bottom: 0;
      z-index: 1099;
      display: flex;
      flex-direction: column;
      min-width: 0;
      background: var(--oc-ground-page);
      box-shadow: inset -1px 0 0 var(--oc-line-rule);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
    }

    .had-grip {
      position: absolute;
      top: 0;
      bottom: 0;
      right: -3px;
      z-index: 2;
      width: 7px;
      cursor: col-resize;
      touch-action: none;
    }

    :global(body:has(.session-sidebar-panel--open)) .had {
      left: var(--sidebar-dock-w);
    }

    .had-grip:hover,
    .had-grip:focus-visible {
      background: color-mix(in srgb, var(--oc-orange) 35%, transparent);
    }
  }
</style>
