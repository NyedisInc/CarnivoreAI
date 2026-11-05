
<script lang="ts">
    import { motionReduced } from '../motion/motion';
    import { onMount } from 'svelte';
    import { fly } from 'svelte/transition';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import IconButton from '../base/IconButton.svelte';
    import { t as appT } from '../i18n/index.svelte';
    import type { Translate } from '../sessions/types';
    import AgentChatFrame from '../../cplugs/huddle/agents/AgentChatFrame.svelte';
    import { openAgentTerminal } from '../../cplugs/huddle/agents/agent-terminal';
    import { addAgentWidget, beginAgentBarDrag, popOutAgent } from './agent-dock';
    import { phoneView } from '../drawer/phone-view.svelte';
    import {
        AGENT_DRAWER_MAX_PX, AGENT_DRAWER_MIN_PX, PHONE_LOCK_CLASS, agentDrawer, closeAgentDrawer, dockBesideTerminal, drawerAnchorLeft, drawerWidth, isEdgeSwipeBack,
        phoneFrame, resetDrawerWidth, setDrawerWidth, widthFromPointer, type PhoneFrame,
    } from './agent-drawer.svelte';

    interface Props {
        t?: Translate;
    }

    const { t = appT }: Props = $props();

    const width = $derived(drawerWidth());
    const phone = $derived(phoneView());
    let frame = $state<PhoneFrame | null>(null);
    let dragging = false;
    const slide = $derived({
        x: phone ? (typeof window === 'undefined' ? 0 : window.innerWidth) : -width,
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

    $effect(() => {
        if (!phone || agentDrawer.id === null) {
            frame = null;
            return;
        }
        const fit = (): void => {
            frame = phoneFrame();
        };
        fit();
        const root = document.documentElement;
        root.classList.add(PHONE_LOCK_CLASS);
        const drawerPanel = document.getElementById('session-sidebar-panel');
        drawerPanel?.style.setProperty('--sidebar-dock-w', '100vw');
        const vv = window.visualViewport;
        vv?.addEventListener('resize', fit);
        vv?.addEventListener('scroll', fit);
        window.addEventListener('resize', fit);
        return () => {
            root.classList.remove(PHONE_LOCK_CLASS);
            drawerPanel?.style.removeProperty('--sidebar-dock-w');
            vv?.removeEventListener('resize', fit);
            vv?.removeEventListener('scroll', fit);
            window.removeEventListener('resize', fit);
        };
    });

    let swipeFrom: { x: number; y: number } | null = null;

    function swipeDown(event: PointerEvent): void {
        swipeFrom = phone && event.pointerType === 'touch' ? { x: event.clientX, y: event.clientY } : null;
    }

    function swipeUp(event: PointerEvent): void {
        if (swipeFrom && frame && isEdgeSwipeBack(swipeFrom, { x: event.clientX, y: event.clientY }, frame.left)) closeWithFocus();
        swipeFrom = null;
    }

    onMount(() => {
        const redock = (): void => {
            dockBesideTerminal(agentDrawer.id !== null, drawerWidth());
        };
        window.addEventListener('resize', redock);
        const onKey = (event: KeyboardEvent): void => {
            if (event.key !== 'Escape' || agentDrawer.id === null || event.defaultPrevented || !panel) return;
            const inside = (node: unknown): boolean => node instanceof Node && panel!.contains(node);
            if (!inside(event.target) && !inside(document.activeElement)) return;
            closeWithFocus();
        };
        window.addEventListener('keydown', onKey);
        return () => {
            window.removeEventListener('resize', redock);
            dockBesideTerminal(false, 0);
            window.removeEventListener('keydown', onKey);
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

{#snippet close()}
    <button type="button" class="oc-ibtn oc-ibtn--bare had-close" data-agent-drawer-close aria-label={t('cplug.huddle.swarm.drawer.close')}
            onclick={closeWithFocus}><Icon name="close" size={12} /></button>
{/snippet}


{#snippet back()}
    <span class="had-back"><IconButton label={t('cplug.huddle.swarm.drawer.back')} icon="back" iconSize={16} variant="quiet" data-agent-drawer-back
                                       onclick={closeWithFocus} /></span>
{/snippet}

{#if agentDrawer.id !== null}
    <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
    <aside class="had" class:had--phone={phone} transition:fly={slide} bind:this={panel} aria-label={t('cplug.huddle.swarm.drawer.label')}
           data-agent-drawer={agentDrawer.id} data-agent-drawer-width={phone ? null : width} data-agent-drawer-phone={phone ? '' : null}
           style:width={phone ? null : `min(${width}px, 85vw)`} style:top={frame ? `${frame.top}px` : null} style:left={frame ? `${frame.left}px` : null}
           style:height={frame ? `${frame.height}px` : null} onpointerdown={swipeDown} onpointerup={swipeUp} onpointercancel={() => (swipeFrom = null)}>
        {#if !phone}
        <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
        <div class="had-grip" role="separator" aria-orientation="vertical" tabindex="0" data-agent-drawer-grip
             aria-label={t('cplug.huddle.swarm.drawer.resize')} aria-valuemin={AGENT_DRAWER_MIN_PX} aria-valuemax={AGENT_DRAWER_MAX_PX} aria-valuenow={width}
             onpointerdown={down} onpointermove={move} onpointerup={up} onpointercancel={up} onkeydown={key} ondblclick={resetDrawerWidth}></div>
        {/if}
        <AgentChatFrame id={agentDrawer.id} bind:tab={agentDrawer.tab} {t} onOpenedTerminal={closeAgentDrawer} onBarDown={phone ? undefined : barDown} menu={menu}
                        lead={phone ? back : undefined} actions={phone ? undefined : close} />
    </aside>
{/if}

<style>
  @layer components {
    .had {
      position: fixed;
      top: max(env(safe-area-inset-top, 0px), var(--desktop-inset-top, 0px));
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

    :global(body.ps-drawer-open) .had:not(.had--phone) {
      left: var(--sidebar-dock-w);
    }

    .had--phone {
      right: 0;
      bottom: auto;
      z-index: 1101;
      overscroll-behavior: contain;
    }

    .had-back {
      display: inline-flex;
      flex: none;
      --oc-ibtn-size: 36px;
    }

    .had--phone :global(.hdc-filter:disabled) {
      display: none;
    }


    .had-grip:hover,
    .had-grip:focus-visible {
      background: color-mix(in srgb, var(--oc-orange) 35%, transparent);
    }
  }

  :global(html.had-phone-open),
  :global(html.had-phone-open body) {
    overflow: hidden;
    overscroll-behavior: none;
  }
</style>
