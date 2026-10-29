
<script lang="ts">
    import { BROWSE_KEYS } from '../../../../client/js/labels/skill-browse.js';
    import Icon from '../../opscenter/ui/Icon.svelte';
    import CascadeMenu from '../drawer-tabs/CascadeMenu.svelte';
    import type { MenuNode } from '../drawer-tabs/add-component-menu';
    import type { AddProject } from './add-projects';
    import type { Translate } from '../sessions/types';

    interface Props {
        projects: readonly AddProject[];
        haveGlobal: boolean;
        installedAt?: readonly string[];
        haveAnyProject?: boolean;
        onAdd: (target: 'global' | 'project', projectPath?: string) => void;
        caret?: boolean;
        act?: string;
        t: Translate;
    }

    const { projects, haveGlobal, installedAt = [], haveAnyProject = false, onAdd, caret = true, act = 'add', t }: Props = $props();

    const globalBlocked = $derived(haveGlobal || haveAnyProject);

    let anchor = $state<HTMLElement | null>(null);

    let caretEl = $state<HTMLElement | null>(null);

    function closeMenu(): void {
        anchor = null;
        caretEl?.focus();
    }

    function pick(target: 'global' | 'project', projectPath?: string): void {
        if (anchor) closeMenu();
        onAdd(target, projectPath);
    }

    const menu = $derived<MenuNode[]>([
        {
            id: 'add-global',
            label: t(BROWSE_KEYS.addGlobal),
            blocked: globalBlocked ? t(BROWSE_KEYS.addHave) : undefined,
            run: () => pick('global'),
        },
        haveGlobal || projects.length === 0
            ? {
                  id: 'add-project',
                  label: t(BROWSE_KEYS.addProject),
                  blocked: haveGlobal ? t(BROWSE_KEYS.addHaveGlobal) : t(BROWSE_KEYS.addNoProject),
              }
            : {
                  id: 'add-project',
                  label: t(BROWSE_KEYS.addProject),
                  children: projects.map((project) => ({
                      id: `add-project:${project.path}`,
                      label: project.name,
                      blocked: installedAt.includes(project.path) ? t(BROWSE_KEYS.addHave) : undefined,
                      run: () => pick('project', project.path),
                  })),
              },
    ]);
</script>

<span class="cat-add">
    <button
        type="button"
        class="cat-add__main"
        data-act={act}
        disabled={globalBlocked}
        onclick={() => pick('global')}
    >{t(BROWSE_KEYS.addAction)}</button>
    {#if caret}
    <button
        type="button"
        class="cat-add__caret"
        data-act="add-menu"
        bind:this={caretEl}
        aria-haspopup="menu"
        aria-expanded={anchor !== null}
        aria-label={t(BROWSE_KEYS.addMenu)}
        onclick={(event) => (anchor = anchor ? null : (event.currentTarget as HTMLElement))}
    ><Icon name="chevron-down" size={10} /></button>
    {/if}
</span>

{#if caret && anchor}
    <CascadeMenu root={menu} {anchor} label={t(BROWSE_KEYS.addMenu)} alignEnd onClose={closeMenu} />
{/if}

<style>
    .cat-add {
        position: relative;
        display: inline-flex;
        align-items: stretch;
        border: 1px solid var(--oc-orange);
        border-radius: var(--oc-control-radius, 2px);
        background: transparent;
    }

    .cat-add:hover {
        border-color: var(--oc-orange-bright);
    }

    .cat-add:has(:focus-visible) {
        border-color: color-mix(in oklab, var(--oc-orange) var(--oc-focus-keep, 75%), var(--oc-focus-lift, currentColor));
    }

    .cat-add:has(.cat-add__main:disabled) {
        border-color: var(--oc-line-rule);
    }

    .cat-add__main,
    .cat-add__caret {
        padding: 3px 10px;
        border: 0;
        border-radius: 0;
        background: transparent;
        color: var(--oc-text-secondary);
        font-size: 11px;
        cursor: pointer;
    }

    .cat-add__main {
        color: var(--oc-text-bright);
    }

    .cat-add__caret {
        padding: 3px 6px;
        color: var(--oc-text-muted);
        border-left: 1px solid color-mix(in oklab, var(--oc-orange) 45%, transparent);
        display: inline-flex;
        align-items: center;
    }

    .cat-add__main:hover:not(:disabled),
    .cat-add__caret:hover {
        background: var(--oc-orange-tint);
        color: var(--oc-text-primary);
    }

    .cat-add__main:disabled {
        color: var(--oc-text-muted);
        cursor: default;
    }

    @media (max-width: 767px) {
        .cat-add__main,
        .cat-add__caret {
            min-height: 44px;
        }
    }

    /* width:767px */
    @media (max-width: 767px) {
        .cat-add__main {
            flex: 1;
            min-width: 44px;
            padding-inline: 12px;
        }

        .cat-add__caret {
            min-width: 44px;
            padding: 0;
        }
    }
</style>
