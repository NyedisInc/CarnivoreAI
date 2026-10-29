
<script lang="ts">
  import { t } from '../../i18n/index.svelte';
  import Button from '../../base/Button.svelte';
  import Field from '../../base/Field.svelte';
  import Select from '../../base/Select.svelte';
  import { data, NO_HOST, sessionOptions, setFilters } from '../page-store.svelte';
  import { automationOptions, statusOptions, triggerOptions, whereOptions, type Opt } from './feed-model';
  import { anySelect, fv, FIRST_LIMIT } from './feed-state.svelte';

  type Props = {
    runs: number;
    changed: number;
    unread: number;
    anyFilter: boolean;
    onMarkRead: () => void;
    onClear: () => void;
  };
  let { runs, changed, unread, anyFilter, onMarkRead, onClear }: Props = $props();

  const statuses = statusOptions();
  const triggers = triggerOptions();
  const autos = $derived(automationOptions(data.automations));
  const wheres = $derived(whereOptions(data.automations, data.projects, sessionOptions()));
  const computers = $derived.by((): Opt[] => {
    const list: Opt[] = (data.counts?.hosts ?? []).map((h) => ({ value: h, label: h }));
    if (data.counts?.has_unrecorded_host) list.push({ value: NO_HOST, label: t('automations.page.feed.computer_unrecorded') });
    return list;
  });
  const more = $derived(fv.filtersOpen || anySelect());

  function pick(patch: Parameters<typeof setFilters>[0]): void {
    fv.limit = FIRST_LIMIT;
    setFilters(patch);
  }

  function local(change: () => void): void {
    change();
    fv.limit = FIRST_LIMIT;
  }

  function toggleMore(): void {
    fv.filtersOpen = !fv.filtersOpen && !anySelect();
  }

  function searchKey(e: KeyboardEvent): void {
    if (e.key !== 'Escape') return;
    local(() => (fv.q = ''));
    (e.currentTarget as HTMLInputElement).blur();
  }
</script>

{#snippet select(id: string, value: string, any: string, aria: string, opts: Opt[], onChange: (v: string) => void)}
  <Select
    size="sm"
    {id}
    aria-label={aria}
    data-on={value ? '' : undefined}
    {value}
    options={[{ value: '', label: any }, ...opts.map((o) => ({ value: o.value, label: o.label }))]}
    onchange={(e) => onChange(e.currentTarget.value)}
  />
{/snippet}

<div class="ap-fd-top" id="ap-fd-top" data-more={String(more)} data-feed-top>
  <div class="ap-fd-row1">
    <Field
      variant="search"
      id="f-q"
      label={t('automations.page.feed.search.aria')}
      placeholder={t('automations.page.feed.search.placeholder')}
      clearLabel={t('automations.page.find.clear')}
      autocomplete="off"
      spellcheck={false}
      bind:value={() => fv.q, (next) => local(() => (fv.q = next))}
      onkeydown={searchKey}
    />
    <Button size="sm" id="f-changed" aria-pressed={fv.changedOnly} onclick={() => local(() => (fv.changedOnly = !fv.changedOnly))}>{t('automations.page.feed.changed_only')}</Button>
    <Button size="sm" id="f-unread" aria-pressed={fv.unreadOnly} onclick={() => local(() => (fv.unreadOnly = !fv.unreadOnly))}>{t('automations.page.feed.unread_only')}</Button>
    <Button size="sm" id="f-more" aria-pressed={more} onclick={toggleMore}>{t('automations.page.feed.filters')}</Button>
  </div>
  <div class="ap-fd-row2">
    {@render select('f-status', data.filters.status, t('automations.page.feed.any_status'), t('automations.page.feed.status_aria'), statuses, (v) => pick({ status: v }))}
    {@render select('f-auto', data.filters.automation, t('automations.page.feed.any_automation'), t('automations.page.feed.automation_aria'), autos, (v) => pick({ automation: v }))}
    {@render select('f-where', data.where, t('automations.page.feed.any_session'), t('automations.page.feed.where_aria'), wheres, (v) => pick({ where: v }))}
    {@render select('f-trigger', data.filters.trigger, t('automations.page.feed.any_trigger'), t('automations.page.feed.trigger_aria'), triggers, (v) => pick({ trigger: v }))}
    {@render select('f-computer', data.filters.host, t('automations.page.feed.any_computer'), t('automations.page.feed.computer_aria'), computers, (v) => pick({ host: v }))}
  </div>
  <div class="ap-fd-meta" data-feed-meta>
    <span class="ap-num">{t('automations.page.feed.meta', { runs, changed, unread })}</span>
    <span class="ap-fd-meta-b">
      {#if unread}<Button size="sm" data-act="mark-read" onclick={onMarkRead}>{t('automations.page.feed.mark_all_read')}</Button>{/if}
      {#if anyFilter}<Button size="sm" data-act="clear" onclick={onClear}>{t('automations.page.clear_filters')}</Button>{/if}
    </span>
  </div>
</div>
