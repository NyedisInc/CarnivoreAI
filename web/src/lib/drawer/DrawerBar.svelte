<script lang="ts">
  /* the account chip */
  import IconButton from '../base/IconButton.svelte';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import { t } from '../i18n/index.svelte';
  import { accountChip } from '../drawer-hud/account-menu.svelte';
  import { cplugBarIndicators } from '../../cplugs/host/readers';
  import { BEAST_BAR_ACTION, beastIndicator } from '../beast-mode/control.svelte';
  import { avatarInnerHtml, isMember } from './avatar';
  import type { BarView } from './bar-view.svelte';

  let { view }: { view: BarView } = $props();

  const who = $derived(view.identity === undefined ? accountChip.identity : view.identity);
  const member = $derived(isMember(who));
  const name = $derived(member ? who!.name : t('drawer.account.lurker'));
  const indicators = $derived([
    ...(beastIndicator.visible() ? [{ action: `${BEAST_BAR_ACTION}${beastIndicator.id}`, name: `beast.${beastIndicator.id}`, item: beastIndicator }] : []),
    ...cplugBarIndicators().map((item) => ({ action: item.action, name: `${item.cplugId}.${item.id}`, item })),
  ]);
</script>

<div class="session-sidebar-bar">
  <div class="session-sidebar-bar__group">
    <button type="button" class="session-sidebar-bar__account" data-bar-action="account" aria-haspopup="menu" aria-expanded="false" aria-label={t('drawer.account.chip', { name })}>
      <span class="session-sidebar-bar__avatar" data-kind={member ? 'member' : 'lurker'} aria-hidden="true">{@html avatarInnerHtml(who)}</span>
      <span class="session-sidebar-bar__account-name">{name}</span>
      <span class="session-sidebar-bar__account-chevron" aria-hidden="true"><Icon name="chevron-up" size={12} /></span>
    </button>
    {#if !member}
      <button type="button" class="session-sidebar-bar__signin" data-btn="secondary" data-bar-action="signin">{t('account.chip.signin')}</button>
    {/if}
  </div>
  <div class="session-sidebar-bar__version">
    {#if view.crown}
      <IconButton label={t('header.master_all')} variant="quiet" icon="crown" iconSize={15} pressed={true} id="sidebarMasterAllBtn"
        data-bar-action="master_all" />
    {/if}
    {#each indicators as { action, name: indicator, item } (action)}
      <IconButton label={item.label()} variant="quiet" icon={item.icon} iconSize={15} data-bar-action={action}
        data-bar-indicator={indicator} data-bar-indicator-quiet={item.tone?.() === 'quiet' ? '' : undefined} />
    {/each}
    {#if view.version}
      {@const v = view.version}
      <div class="version-footer">
        {#if v.href}
          <a class="version-footer__link" href={v.href} target="_blank" rel="noopener noreferrer"><span class="version">{v.text}{#if v.preview}<span class="version-footer__preview">{v.previewText}</span>{/if}</span></a>
        {:else}
          <span class="version">{v.text}</span>
        {/if}
      </div>
    {/if}
  </div>
</div>
