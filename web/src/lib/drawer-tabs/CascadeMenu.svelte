<script lang="ts">
  import { flushSync, untrack } from 'svelte';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import { t } from '../i18n/index.svelte';
  import { truncatedTip } from '../tooltip/truncated-tip';
  import SessionFace from '../sessions/SessionFace.svelte';
  import { placeMenu, placeMenuAbove, type MenuNode, type Placement } from './add-component-menu';
  import { assignMenuKeys, pressMenuKey } from '../menu-keys/menu-keys';
  import MenuKey from '../menu-keys/MenuKey.svelte';
  import ProjectColorRow from '../project-colors/ProjectColorRow.svelte';
  import { claimOpenMenu } from './open-menu';
  import { findByPath, isRemotable, nextRemoteMenuId, remoteMenuHost, toWire } from './menu-remote';

  let {
    root,
    anchor,
    label,
    status = '',
    onClose,
    nestedIn = null,
    above = false,
    heading = '',
    subheading = '',
    wide = false,
    alignEnd = false,
    panelId = undefined,
  }: {
    root: MenuNode[];
    anchor: HTMLElement | null;
    label: string;
    status?: string;
    onClose: () => void;
    nestedIn?: HTMLElement | null;
    above?: boolean;
    heading?: string;
    subheading?: string;
    wide?: boolean;
    alignEnd?: boolean;
    panelId?: string;
  } = $props();

  const remote = untrack(() => (isRemotable(root) ? remoteMenuHost() : null));
  const remoteId = nextRemoteMenuId();
  $effect(() => {
    if (!remote) return;
    const box = anchor?.getBoundingClientRect();
    remote.show(
      remoteId,
      { label, anchor: box ? { left: box.left, top: box.top, right: box.right, bottom: box.bottom } : null, nodes: toWire(root) },
      { choose: (chosen) => findByPath(root, chosen)?.run?.(), close: () => onClose() },
    );
  });
  $effect(() => () => remote?.hide(remoteId));

  let path = $state<string[]>([]);
  let panels = $state<(HTMLElement | null)[]>([]);
  let places = $state<Placement[]>([]);

  const levels = $derived.by(() => {
    const out: MenuNode[][] = [root];
    for (const id of path) {
      const next = out[out.length - 1]?.find((node) => node.id === id)?.children;
      if (!next) break;
      out.push(next);
    }
    return out;
  });

  function close(): void {
    const back = anchor;
    onClose();
    back?.focus({ preventScroll: true });
  }

  const items = (level: number): HTMLElement[] =>
    [...(panels[level]?.querySelectorAll<HTMLElement>('[role="menuitem"], [role="menuitemradio"], [role="menuitemcheckbox"]') ?? [])];

  const itemFor = (level: number, id: string): HTMLElement | undefined =>
    items(level).find((el) => el.dataset.node === id);

  function open(level: number, node: MenuNode, focusInto: boolean): void {
    path = [...path.slice(0, level), node.id];
    if (!focusInto) return;
    flushSync();
    items(level + 1)[0]?.focus();
  }

  function closeBelow(level: number): void {
    const opener = path[level];
    path = path.slice(0, level);
    if (opener) itemFor(level, opener)?.focus();
  }

  const FLASH_MS = 700;
  let flashed = $state<{ id: string; label: string } | null>(null);

  function runFlash(node: MenuNode, flash: NonNullable<MenuNode['flash']>): void {
    flash.run().then((ok) => {
      if (!ok) { close(); return; }
      flashed = { id: node.id, label: flash.done };
      setTimeout(close, FLASH_MS);
    }, (err: unknown) => {
      console.error(`[CascadeMenu] "${node.id}" failed:`, err);
      close();
    });
  }

  function activate(level: number, node: MenuNode, event: MouseEvent): void {
    if (node.blocked) return;
    if (node.flash) { runFlash(node, node.flash); return; }
    if (node.children) open(level, node, event.detail === 0);
    else node.run?.();
  }

  function hover(level: number, node: MenuNode): void {
    if (node.children && !node.blocked) open(level, node, false);
    else if (path.length > level) path = path.slice(0, level);
  }

  const keysOf = (nodes: MenuNode[]): string[] =>
    assignMenuKeys(nodes.map((n) => ({ id: n.id, label: n.label, skip: !!n.blocked || !!n.swatches })));

  function onKeydown(level: number, event: KeyboardEvent): void {
    if (pressMenuKey(event, panels[level])) return;
    const list = items(level);
    const at = list.indexOf(event.target as HTMLElement);
    const node = levels[level]?.find((n) => n.id === (event.target as HTMLElement).dataset.node);
    let next = -1;
    if (event.key === 'ArrowDown') next = (at + 1) % list.length;
    else if (event.key === 'ArrowUp') next = (at - 1 + list.length) % list.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = list.length - 1;
    else if (event.key === 'ArrowRight') {
      event.preventDefault();
      if (node?.children && !node.blocked) open(level, node, true);
      return;
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault();
      if (level > 0) { closeBelow(level - 1); return; }
      if (nestedIn) close();
      return;
    } else if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      if (path.length > 0) closeBelow(path.length - 1);
      else close();
      return;
    } else if (event.key === 'Tab') {
      onClose();
      return;
    }
    if (next < 0 || list.length === 0) return;
    event.preventDefault();
    list[next]?.focus();
  }

  function onWindowKeydown(event: KeyboardEvent): void {
    if (event.key !== 'Escape' || event.defaultPrevented) return;
    const target = event.target as Node | null;
    if (target && panels.some((p) => p?.contains(target))) return;
    event.preventDefault();
    if (path.length > 0) closeBelow(path.length - 1);
    else close();
  }

  const isInside = (node: Node | null): boolean =>
    !!node && (!!anchor?.contains(node) || !!nestedIn?.contains(node) || panels.some((p) => p?.contains(node)));

  function onOutside(event: PointerEvent): void {
    const target = event.target as Node | null;
    if (!target || isInside(target)) return;
    onClose();
  }

  function onFocusIn(event: FocusEvent): void {
    const target = event.target as Node | null;
    if (!target || isInside(target)) return;
    onClose();
  }

  function onWindowBlur(): void {
    setTimeout(() => {
      if (document.activeElement instanceof HTMLIFrameElement && !isInside(document.activeElement)) onClose();
    }, 0);
  }

  function place(): void {
    if (typeof window === 'undefined') return;
    for (const panel of panels) {
      if (panel && !panel.matches(':popover-open')) panel.showPopover();
    }
    const view = { width: window.innerWidth, height: window.innerHeight };
    const next: Placement[] = [];
    levels.forEach((_, level) => {
      const panel = panels[level];
      const size = { width: panel?.offsetWidth ?? 0, height: panel?.offsetHeight ?? 0 };
      const prev = next[level - 1];
      if (level === 0 || !prev) {
        const r = anchor?.getBoundingClientRect();
        const opener = r ? { left: r.left, top: r.top, right: r.right, bottom: r.bottom } : { left: 0, top: 0, right: 0, bottom: 0 };
        const parentBox = level === 0 && nestedIn ? nestedIn.getBoundingClientRect() : null;
        const placed = level === 0 && above && !parentBox ? placeMenuAbove(opener, size, view) : placeMenu(opener, parentBox, size, view);
        if (level === 0 && alignEnd && !parentBox) {
          placed.left = Math.max(0, Math.min(opener.right - size.width, view.width - size.width));
        }
        next.push(placed);
        return;
      }
      const prevPanel = panels[level - 1];
      const right = prev.left + (prevPanel?.offsetWidth ?? 0);
      const top = prev.top + (itemFor(level - 1, path[level - 1] ?? '')?.offsetTop ?? 0) - (prevPanel?.scrollTop ?? 0);
      next.push(placeMenu({ left: prev.left, right, top, bottom: top }, { left: prev.left, right, top: prev.top, bottom: prev.top }, size, view));
    });
    places = next;
  }

  $effect(() => {
    void levels.length;
    void path.join('/');
    place();
  });

  $effect(() => (nestedIn ? undefined : claimOpenMenu(() => onClose())));

  let focused = false;
  $effect(() => {
    if (focused || !panels[0]) return;
    focused = true;
    items(0)[0]?.focus({ preventScroll: true });
  });
</script>

<svelte:window onpointerdowncapture={onOutside} onfocusin={onFocusIn} onblur={onWindowBlur} onresize={place} onkeydown={onWindowKeydown} />


{#each remote ? [] : levels as nodes, level (level)}
  {@const at = places[level]}
  {@const keys = keysOf(nodes)}
  {@const iconSlot = nodes.some((node) => node.icon || node.glyphHtml)}
  <div
    class="acm-menu popup-focus"
    data-oc-base
    class:acm-menu--wide={wide}
    popover="manual"
    role="menu"
    tabindex="-1"
    data-level={level}
    id={level === 0 ? panelId : undefined}
    aria-label={level === 0 ? label : (levels[level - 1]?.find((n) => n.id === path[level - 1])?.label ?? '')}
    style={at ? `left: ${Math.round(at.left)}px; top: ${Math.round(at.top)}px; max-height: ${Math.round(at.maxHeight)}px` : 'left: 0; top: 0; opacity: 0'}
    bind:this={panels[level]}
    onkeydown={(event) => onKeydown(level, event)}
  >
    {#if level === 0 && heading}
      <p class="acm-heading">{heading}{#if subheading}<span class="acm-heading__sub">{subheading}</span>{/if}</p>
    {/if}
    {#each nodes as node, i (node.id)}
      {#if node.swatches}
        {@const swatches = node.swatches}
        <div class="acm-swatches" class:acm-sep={node.sep} role="group" data-heading-menu-colors data-node={node.id}>
          <ProjectColorRow value={swatches.value} id={`acm-color-${node.id}`} {t} allowNone={swatches.allowNone === true} onPick={(key) => swatches.onPick(key)} onPreview={swatches.onPreview} />
        </div>
      {:else}
      <button data-base-exempt="cascade-menu-item-base-has-no-menu-item"
        type="button"
        role={node.checked === undefined ? 'menuitem' : node.toggle ? 'menuitemcheckbox' : 'menuitemradio'}
        class="acm-item"
        class:acm-sep={node.sep}
        class:acm-item--danger={node.danger}
        class:acm-item--update={node.tone === 'update'}
        class:acm-locked={node.locked}
        tabindex="-1"
        data-node={node.id}
        data-menu-key={keys[i] || undefined}
        title={node.blocked ? undefined : node.title}
        data-tooltip={node.blocked || undefined}
        {...(node.blocked ? { 'aria-description': node.blocked } : {})}
        aria-haspopup={node.children ? 'menu' : undefined}
        aria-expanded={node.children ? path[level] === node.id : undefined}
        aria-checked={node.checked}
        aria-disabled={node.blocked ? 'true' : undefined}
        onclick={(event) => activate(level, node, event)}
        onpointerenter={() => hover(level, node)}
      >
        {#if node.toggle && node.checked !== undefined}<span class="acm-box" class:acm-box--on={node.checked} aria-hidden="true"></span>{/if}
        {#if node.agent}<SessionFace facts={node.agent} mark />
        {:else if node.aggregateLightHtml}<span class="acm-agg-led">{@html node.aggregateLightHtml}</span>
        {:else if node.glyphHtml}<span class="acm-icon" aria-hidden="true">{@html node.glyphHtml}</span>
        {:else if node.icon}<span class="acm-icon"><Icon name={node.icon} size={14} /></span>
        {:else if iconSlot}<span class="acm-icon" aria-hidden="true"></span>{/if}
        <span class="acm-label" use:truncatedTip={node.label} aria-live={node.flash ? 'polite' : undefined}>{flashed?.id === node.id ? flashed.label : node.label}</span>
        {#if node.desc}<span class="acm-desc">{node.desc}</span>{/if}
        {#if node.locked}<span class="acm-lock"><span class="acm-lock-star" aria-hidden="true"><Icon name="star" size={12} /></span>{t('account.lock.cta')}</span>
        {:else if node.badge}<span class="acm-why">{node.badge}</span>
        {:else if node.hint}<kbd class="acm-hint">{node.hint}</kbd>
        {:else}<MenuKey key={keys[i] ?? ''} />{/if}
        {#if node.children}<span class="acm-chevron"><Icon name="chevron-right" size={12} /></span>{/if}
      </button>
      {/if}
    {/each}
    {#if level === 0 && status}
      <p class="acm-refused" role="status">{status}</p>
    {/if}
  </div>
{/each}

<style>
  @layer components {
    .acm-menu {
      position: fixed;
      inset: auto;
      margin: 0;
      z-index: 45;
      display: flex;
      flex-direction: column;
      min-width: 180px;
      max-width: 280px;
      padding: var(--oc-space-1);
      overflow-y: auto;
      border-radius: var(--oc-radius);
    }

    .acm-menu--wide {
      min-width: 220px;
      max-width: 340px;
    }

    .acm-item {
      display: flex;
      align-items: center;
      gap: var(--oc-space-2);
      box-sizing: border-box;
      min-height: 28px;
      padding: 0 var(--oc-space-2);
      line-height: 16px;
      background: none;
      border: 0;
      border-radius: var(--oc-radius);
      color: var(--oc-text-secondary);
      font: inherit;
      font-size: var(--oc-fs-body);
      text-align: left;
      cursor: pointer;
    }

    .acm-item:hover:not([aria-disabled='true']),
    .acm-item:focus-visible,
    .acm-item[aria-expanded='true'] {
      background: var(--oc-ground-hover);
      color: var(--oc-text-primary);
      outline: none;
    }

    .acm-sep {
      position: relative;
      margin-top: var(--oc-space-2);
    }

    .acm-sep::before {
      content: '';
      position: absolute;
      top: calc(var(--oc-space-1) * -1 - 1px);
      right: 0;
      left: 0;
      height: 1px;
      background: var(--oc-line-rule);
      pointer-events: none;
    }

    .acm-swatches {
      padding: var(--oc-space-1) var(--oc-space-2);
    }

    .acm-item--danger:not([aria-disabled='true']) {
      color: var(--oc-coral);
    }

    .acm-item--update:not([aria-disabled='true']),
    .acm-item--update:not([aria-disabled='true']):hover,
    .acm-item--update:not([aria-disabled='true']):focus-visible {
      color: var(--oc-green);
    }

    .acm-item[aria-disabled='true'] {
      color: var(--oc-text-dim);
      cursor: default;
    }

    .acm-item[aria-disabled='true'][role='menuitemcheckbox'] {
      opacity: 0.45;
    }

    .acm-box {
      display: grid;
      flex: none;
      place-items: center;
      width: 12px;
      height: 12px;
      border: 1px solid var(--oc-control-line-hi);
      border-radius: 1px;
    }

    .acm-box--on {
      border-color: var(--oc-green);
    }

    .acm-box--on::after {
      content: '';
      width: 6px;
      height: 6px;
      background: var(--oc-green);
    }

    .acm-label {
      min-width: 0;
      line-height: inherit;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .acm-agg-led {
      display: inline-flex;
      flex: none;
      align-items: center;
    }

    .acm-item[aria-checked='true'] .acm-label {
      color: var(--oc-orange);
    }

    .acm-desc {
      min-width: 0;
      overflow: hidden;
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-label);
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .acm-menu--wide .acm-label {
      flex: 0 0 auto;
    }

    .acm-why,
    .acm-refused {
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-label);
    }

    .acm-why {
      flex: 0 1 auto;
      min-width: 0;
      margin-left: auto;
      overflow: hidden;
      text-align: right;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .acm-item:has(.acm-why) .acm-label {
      flex: none;
    }

    .acm-locked .acm-label {
      color: var(--oc-text-dim);
    }

    .acm-lock {
      display: inline-flex;
      flex: 0 0 auto;
      align-items: center;
      gap: var(--oc-space-1);
      margin-left: auto;
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-label);
    }

    .acm-lock-star {
      display: inline-grid;
      place-items: center;
      line-height: 0;
      color: var(--oc-yellow-bright);
    }

    .acm-chevron {
      display: grid;
      place-items: center;
      margin-left: auto;
      line-height: 0;
      color: var(--oc-text-dim);
    }

    .acm-item :global(.menu-key + .acm-chevron) {
      margin-left: var(--oc-space-1);
    }

    .acm-chevron :global(svg) {
      display: block;
    }

    .acm-heading {
      box-sizing: border-box;
      display: flex;
      align-items: center;
      min-height: 28px;
      margin: 0 0 var(--oc-space-1);
      padding: 0 var(--oc-space-2);
      line-height: 16px;
      overflow: hidden;
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-label);
      letter-spacing: var(--oc-tracking-label);
      text-overflow: ellipsis;
      white-space: nowrap;
      box-shadow: 0 1px 0 0 var(--oc-line-rule);
    }

    .acm-heading__sub {
      min-width: 0;
      margin-left: var(--oc-space-2);
      overflow: hidden;
      text-overflow: ellipsis;
    }

    .acm-icon {
      display: grid;
      flex: none;
      place-items: center;
      width: 14px;
      height: 14px;
      line-height: 0;
    }

    .acm-icon :global(svg) {
      display: block;
    }

    .acm-hint {
      flex: 0 0 auto;
      margin-left: auto;
      padding-left: var(--oc-space-3);
      color: var(--oc-text-dim);
      font-family: var(--font-mono);
      font-size: var(--oc-fs-label);
    }

    .acm-item[aria-checked='true'][role='menuitemcheckbox'] .acm-icon {
      color: var(--oc-orange);
    }

    .acm-refused {
      margin: 0;
      padding: var(--oc-space-1) var(--oc-space-2);
      line-height: 16px;
    }
  }
</style>
