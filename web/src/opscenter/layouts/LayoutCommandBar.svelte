
<script lang="ts">
    import Button from '../../lib/base/Button.svelte';
    import IconButton from '../../lib/base/IconButton.svelte';
    import CascadeMenu from '../../lib/drawer-tabs/CascadeMenu.svelte';
    import type { MenuNode } from '../../lib/drawer-tabs/add-component-menu';
    import { t } from '../../lib/i18n/index.svelte';
    import { uiPrefs } from '../../lib/ui/prefs.svelte';
    import { layoutActive, layoutMode } from './mode.svelte';
    import { broadcastLine, layoutError, type LayoutMember } from './api';
    import { broadcastOn, memberName, recipients, toggleBroadcast } from './broadcast.svelte';
    import { CommandBar } from './command-bar.svelte';
    import LayoutSkillMenu from './LayoutSkillMenu.svelte';
    import { SkillComplete } from './skill-complete.svelte';
    import { layoutSearch } from './layout-search.svelte';
    import LayoutTabs from './LayoutTabs.svelte';

    function confirmBusy(names: string[]): Promise<boolean> {
        const app = (globalThis as { App?: { showConfirmModal?: (
            title: string, message: string, details: string | null, primary: string, secondary: string,
        ) => Promise<boolean> } }).App;
        if (typeof app?.showConfirmModal !== 'function') return Promise.resolve(true);
        return app.showConfirmModal(
            t('layout.bar.busy.title'), t('layout.bar.busy.message', { names: names.join(', ') }),
            t('layout.bar.busy.detail'), t('layout.bar.busy.confirm'), t('layout.bar.busy.cancel'),
        );
    }

    const bar = new CommandBar({
        search: layoutSearch,
        send: (text) => broadcastLine(layoutMode.uuid, text),
        recipients,
        confirmBusy,
        nameOf: (rowId) => {
            const member = layoutMode.members.find((one) => one.session_row_id === rowId);
            return member ? memberName(member) : String(rowId);
        },
        reason: (error) => layoutError(error).detail,
    });

    const skills = new SkillComplete({
        layoutUuid: () => layoutMode.uuid,
        put: (text) => { bar.input(text); inputEl?.focus({ preventScroll: true }); },
    });
    $effect(() => skills.update(bar.text, bar.mode === 'command'));
    let inputEl = $state<HTMLTextAreaElement | null>(null);
    let menuOpen = $state(false);
    let menuAnchor = $state<HTMLElement | null>(null);

    const shown = $derived(layoutActive() && !layoutMode.naming);
    const searching = $derived(bar.mode === 'search');
    const who = $derived(recipients());
    const members = $derived([...layoutMode.members].sort((a, b) => a.position - b.position));

    let openFor = '';
    $effect(() => {
        const uuid = layoutMode.uuid;
        if (uuid === openFor) return;
        openFor = uuid;
        bar.clear();
    });

    const countText = $derived.by(() => {
        if (!layoutSearch.query) return '';
        const total = layoutSearch.total;
        if (total === null) return '';
        if (total === 0) return t('layout.bar.no_matches');
        const at = layoutSearch.position;
        return at !== null ? t('layout.bar.match_of', { index: at, count: total }) : t('layout.bar.matches', { count: total });
    });

    function onKey(event: KeyboardEvent): void {
        if (!event.shiftKey && skills.key(event.key)) {
            event.preventDefault();
            event.stopPropagation();
            return;
        }
        const outcome = bar.key(event.key, event.shiftKey);
        if (outcome === 'ignored') return;
        event.preventDefault();
        event.stopPropagation();
        if (outcome === 'blur') inputEl?.blur();
    }

    function pick(mode: 'search' | 'command'): void {
        bar.setMode(mode);
        inputEl?.focus({ preventScroll: true });
    }

    function fit(): void {
        if (!inputEl) return;
        inputEl.style.height = 'auto';
        inputEl.style.height = `${inputEl.scrollHeight}px`;
    }

    $effect(() => {
        void bar.text;
        fit();
        if (!inputEl) return;
        let width = inputEl.clientWidth;
        const watch = new ResizeObserver(() => {
            if (inputEl && inputEl.clientWidth !== width) {
                width = inputEl.clientWidth;
                fit();
            }
        });
        watch.observe(inputEl);
        return () => watch.disconnect();
    });

    function onInput(event: Event): void {
        const el = event.currentTarget as HTMLTextAreaElement;
        const clean = el.value.replace(/[\r\n]+/g, ' ');
        if (clean !== el.value) el.value = clean;
        bar.input(clean);
    }

    function togglePromptsOnly(): void {
        uiPrefs.setSearchPromptsOnly(!uiPrefs.searchPromptsOnly);
        if (layoutSearch.query) layoutSearch.run(layoutSearch.query);
    }

    const recipientNodes = $derived<MenuNode[]>(members.map((member): MenuNode => {
        const on = broadcastOn(member);
        return {
            id: `recipient:${member.session_row_id}`,
            label: memberName(member),
            checked: on,
            toggle: true,
            keepOpen: true,
            title: t(on ? 'layout.broadcast.on' : 'layout.broadcast.off'),
            run: () => void flip(member),
        };
    }));

    async function flip(member: LayoutMember): Promise<void> {
        const refused = await toggleBroadcast(member);
        if (refused) bar.line = t('layout.broadcast.failed', { reason: refused });
    }
</script>

{#if shown}
    <section class="lcb" aria-label={t('layout.bar.label')} data-layout-bar={layoutMode.uuid}>
        <div class="lcb__tabs"><LayoutTabs /></div>
        <div class="lcb__slot">
        <div class="lcb__box oc-focus-host" data-mode={bar.mode}>
            <span class="lcb__modes" role="group" aria-label={t('layout.bar.modes')}>
                <IconButton label={t('layout.bar.mode_search')} variant="quiet" icon="search" iconSize={13} data-bar-toggle="search"
                    pressed={searching} onclick={() => pick('search')} />
                <IconButton label={t('layout.bar.mode_command')} variant="quiet" icon="chevron-right" iconSize={15} data-bar-toggle="command"
                    pressed={!searching} onclick={() => pick('command')} />
            </span>
            
            <textarea
                data-base-exempt="borderless auto-growing textarea inside the bar's own focus frame (base Field draws a bounded box and gives no element)"
                bind:this={inputEl}
                class="lcb__input"
                rows="1"
                value={bar.text}
                oninput={onInput}
                onkeydown={onKey}
                placeholder={searching ? t('layout.bar.search_placeholder') : t('layout.bar.command_placeholder')}
                aria-label={searching ? t('layout.bar.input_search') : t('layout.bar.input_command')}
                autocomplete="off"
                {...{ autocorrect: "off" }}
                autocapitalize="off"
                spellcheck="false"
                role="combobox"
                aria-expanded={skills.open}
                aria-controls="lcb-skills"
                aria-activedescendant={skills.open ? `lcb-skill-${skills.active}` : undefined}
            ></textarea>
            <LayoutSkillMenu complete={skills} />
            {#if searching}
                <span class="lcb__count" aria-live="polite">{countText}</span>
                <span class="lcb__extra">
                    <IconButton label={t('search.prompts_only.toggle')} variant="quiet" data-bar-tool="prompts-only"
                        pressed={uiPrefs.searchPromptsOnly} onclick={togglePromptsOnly}>
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                            <path d="m3 5 7 7-7 7m10 0h8" stroke="currentColor" stroke-width="1.5"
                                stroke-linecap="round" stroke-linejoin="round" />
                        </svg>
                    </IconButton>
                    <IconButton label={t('layout.bar.prev')} variant="quiet" icon="chevron-up" iconSize={15} data-bar-tool="prev"
                        onclick={() => layoutSearch.step('prev')} />
                    <IconButton label={t('layout.bar.next')} variant="quiet" icon="chevron-down" iconSize={15} data-bar-tool="next"
                        onclick={() => layoutSearch.step('next')} />
                </span>
            {:else}
                <Button size="sm" bind:element={menuAnchor} data-bar-tool="recipients"
                    data-none={who.receiving === 0 ? '' : undefined} aria-haspopup="menu" aria-expanded={menuOpen} onclick={() => { menuOpen = !menuOpen; }}
                    >{t('layout.bar.recipients', { count: who.receiving, total: who.total })}</Button>
            {/if}
        </div>
        </div>
        <span class="lcb__line" class:lcb__line--empty={!bar.line} aria-live="polite">{bar.line}</span>
    </section>
    {#if menuOpen && !searching}
        <CascadeMenu root={recipientNodes} anchor={menuAnchor} label={t('layout.bar.recipients_menu')} onClose={() => { menuOpen = false; }} />
    {/if}
{/if}

<style>
  @layer components {
      .lcb {
          display: flex;
          align-items: center;
          gap: calc(var(--oc-space-2) + var(--oc-space-0-5));
          min-width: 0;
          min-height: calc(var(--oc-titlerow-h-short, 31px) + 5px);
          padding: 0 var(--oc-space-3);
          background: var(--oc-ground-tab-inactive);
          box-shadow: inset 0 -1px 0 0 var(--oc-line-rule);
          font-family: var(--font-mono);
          box-sizing: border-box;
      }

      .lcb__tabs {
          display: flex;
          margin-top: 5px;
          align-self: stretch;
          flex: 0 1 auto;
          max-width: 40%;
          min-width: 0;
      }

      .lcb__slot {
          position: relative;
          flex: 0 1 410px;
          min-width: 0;
          height: 28px;
          margin-left: auto;
      }

      .lcb__box {
          display: flex;
          align-items: flex-start;
          gap: var(--oc-space-0-5);
          position: absolute;
          top: 0;
          left: 0;
          right: 0;
          z-index: 5;
          min-height: 28px;
          padding: 0 var(--oc-space-1) 0 var(--oc-space-0-5);
          --_bd: var(--oc-line-panel);
          --oc-focus-keep: 92%;
          border: 1px solid var(--oc-line-panel);
          border-radius: 3px;
          background: var(--oc-ground-raised);
          box-sizing: border-box;
      }

      .lcb__modes,
      .lcb__extra {
          display: flex;
          align-items: center;
          gap: var(--oc-space-0-5);
          flex: none;
          margin-top: var(--oc-space-0-5);
      }

      .lcb__modes {
          padding-right: var(--oc-space-1);
          box-shadow: inset -1px 0 0 0 var(--oc-line-faint);
      }

      .lcb__modes [aria-pressed='false'] {
          opacity: 0.4;
      }

      .lcb__modes [aria-pressed='false']:hover {
          opacity: 1;
      }

      .lcb__input {
          flex: 1 1 auto;
          min-width: 0;
          max-height: 160px;
          margin: 0;
          padding: var(--oc-space-1) var(--oc-space-1-5);
          line-height: 18px;
          resize: none;
          overflow-y: auto;
          box-sizing: border-box;
          border: 0;
          background: transparent;
          color: var(--oc-text-primary);
          font-family: var(--font-mono);
          font-size: var(--oc-fs-status);
          outline: none;
      }

      .lcb__input::placeholder {
          color: var(--oc-text-muted);
      }

      .lcb__count {
          flex: none;
          padding: var(--oc-space-1-5) var(--oc-space-1-5) 0;
          color: var(--oc-text-secondary);
          font-size: var(--oc-fs-micro, var(--oc-fs-micro));
          letter-spacing: var(--oc-tracking-label, 0.6px);
          text-transform: uppercase;
          white-space: nowrap;
      }


      [data-bar-tool='recipients'][data-none] {
          --_btn-ink: var(--oc-yellow);
          border-color: var(--oc-yellow);
      }

      .lcb__line {
          flex: 0 1 auto;
          min-width: 0;
          color: var(--oc-text-secondary);
          font-size: var(--oc-fs-micro, var(--oc-fs-micro));
          letter-spacing: var(--oc-tracking-label, 0.6px);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
      }

      .lcb__line--empty {
          display: none;
      }

      @media (min-width: 601px) {
          .lcb {
              display: grid;
              grid-template-columns: 1fr auto minmax(0, max(200px, min(410px, calc(100% - 600px))));
          }

          .lcb__tabs {
              grid-column: 1;
              justify-self: start;
              max-width: 100%;
          }

          .lcb__slot {
              grid-column: 3;
              margin-left: 0;
          }

          .lcb__line {
              grid-column: 2;
              justify-self: end;
          }
  }

      @media (max-width: 600px) {
          .lcb {
              gap: var(--oc-space-1-5);
              padding: 0 var(--oc-space-2);
          }

          .lcb__extra,
          .lcb__line {
              display: none;
          }
  }

      @media (pointer: coarse) {
          .lcb {
              min-height: 48px;
          }

          .lcb__slot {
              height: 40px;
          }

          .lcb__box {
              min-height: 40px;
          }

          .lcb__input {
              padding: calc(var(--oc-space-2) + var(--oc-space-0-5)) var(--oc-space-1-5);
          }

  }
  }
</style>
