<script lang="ts">
  import { t } from '../../lib/i18n/index.svelte';
  import SearchField from '../ui/SearchField.svelte';
  import { toggleIn, removeField, type LogFilter } from './filter';
  import { LOG_LEVELS, type LevelState } from './types';
  import { toggleLevel } from './log-levels';
  import { formatUntil } from './level-expiry';

  interface Props {
    filter: LogFilter;
    sources: readonly string[];
    patternError: string | null;
    level: LevelState | null;
    levelBusy: boolean;
    onFilter: (next: LogFilter) => void;
    onLevel: (level: string | null) => void;
    onExport: () => void;
    onClear: () => void;
  }

  const { filter, sources, patternError, level, levelBusy, onFilter, onLevel, onExport, onClear }: Props = $props();

  const ENV_CHOICE = '';
</script>

<div class="oc-rc-bar oc-lv-bar" data-log-toolbar>
  <div class="oc-lv-group" role="group" aria-label={t('opscenter.log.levels')} data-log-levels>
    {#each LOG_LEVELS as name (name)}
      <button type="button" class="oc-btn oc-btn--sm oc-lv-level" data-level={name} aria-pressed={filter.levels.includes(name)}
        onclick={() => onFilter({ ...filter, levels: toggleLevel(filter.levels, name) })}
        >{t(`opscenter.log.level.${name}`)}</button>
    {/each}
  </div>
  {#if sources.length > 1}
    <div class="oc-lv-group" role="group" aria-label={t('opscenter.log.sources')} data-log-sources>
      {#each sources as source (source)}
        <button type="button" class="oc-chip" aria-pressed={!filter.hiddenSources.includes(source)} data-log-source={source}
          onclick={() => onFilter({ ...filter, hiddenSources: toggleIn(filter.hiddenSources, source) })}>{source}</button>
      {/each}
    </div>
  {/if}
  <span class="oc-lv-spacer"></span>
  {#if level}
    <label class="oc-lv-server-level">
      <span class="oc-label">{t('opscenter.log.server_level')}</span>
      <select class="oc-field" disabled={levelBusy} data-log-server-level aria-label={t('opscenter.log.server_level.aria')}
        value={level.source === 'setting' || level.expires_at ? level.level : ENV_CHOICE}
        onchange={(event) => {
          const value = (event.currentTarget as HTMLSelectElement).value;
          onLevel(value === ENV_CHOICE ? null : value);
        }}>
        <option value={ENV_CHOICE}>{t('opscenter.log.server_level.env', { level: level.env_level })}</option>
        {#each level.choices as choice (choice)}
          <option value={choice}>{t(`opscenter.log.level.${choice}`)}</option>
        {/each}
      </select>
      {#if level.expires_at}
        <span class="oc-label" data-log-server-level-until>{t('opscenter.log.server_level.until', { time: formatUntil(level.expires_at) })}</span>
      {/if}
    </label>
  {/if}
  <button type="button" class="oc-btn oc-btn--sm" onclick={onExport} data-log-export>{t('opscenter.log.export')}</button>
  <button type="button" class="oc-btn oc-btn--sm" onclick={onClear} data-log-clear>{t('opscenter.log.clear')}</button>
</div>
<div class="oc-lv-filters" data-log-filters>
  <SearchField value={filter.text} onInput={(text) => onFilter({ ...filter, text })} placeholder={t('opscenter.log.search.placeholder')}
    ariaLabel={t('opscenter.log.search.label')} data-log-text="" />
  <SearchField value={filter.session} onInput={(session) => onFilter({ ...filter, session })} placeholder={t('opscenter.log.session.placeholder')}
    ariaLabel={t('opscenter.log.session.label')} data-log-session="" />
  {#if !filter.fields.length}
    <span class="oc-lv-flash">{t('opscenter.log.field.hint')}</span>
  {:else}
    <div class="oc-lv-group" role="group" aria-label={t('opscenter.log.fields')} data-log-chips>
      {#each filter.fields as chip, i (chip.key + '\u0000' + chip.value)}
        <button type="button" class="oc-chip" aria-pressed="true" data-exclude={chip.exclude ? '' : undefined}
          aria-label={t('opscenter.log.field.remove', { key: chip.key })} onclick={() => onFilter(removeField(filter, i))}
          >{chip.key}{chip.exclude ? ' != ' : ' = '}{chip.value} x</button>
      {/each}
    </div>
  {/if}
  {#if patternError}
    <p class="oc-lv-error" role="status" data-log-pattern-error>{t('opscenter.log.pattern_error', { error: patternError })}</p>
  {/if}
</div>
