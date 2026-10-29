<script lang="ts">
  import { t } from '../../sdk';
  import { Check } from '../../sdk/ui';
  import Character from './characters/Character.svelte';
  import {
    ALL_STATES, ANIMATIONS, COLOR_MODES, HOME_SHAPES, LOOK_RANKS, NO_ANIMATION, SHAPE_NAMES, STATES, swarmLook, type CharacterState, type LookRank,
  } from './characters';
  import { byProject, byRandom, colorOfMember, placeFamilies, type ColorMember } from './characters/family';
  import { swarmGround } from './ground.svelte';
  import {
    FOLLOW_THEME, OPTIONAL_LIMITS, PAGE_VIEWS, PANEL_DENSITIES, UPPER_POSTURES, swarmChoices, swarmSettings, saveSwarmSettings, type OptionalLimit,
    type SwarmPageSettings, type SwarmSettingsChange,
  } from './swarm-settings.svelte';

  let busy = $state(false);
  let failed = $state(false);
  const rows = ['page_default_view', 'panel_default_density', 'character_pack', 'upper_ranks_permissions'] as const;
  const CLOSEOUT_MIN = 1;
  const CLOSEOUT_MAX = 1440;

  async function chooseCloseout(input: HTMLInputElement): Promise<void> {
    const minutes = Number(input.value);
    if (!Number.isInteger(minutes) || minutes < CLOSEOUT_MIN || minutes > CLOSEOUT_MAX) {
      input.value = String(swarmSettings.closeout_window_minutes);
      return;
    }
    if (minutes !== swarmSettings.closeout_window_minutes) await save({ closeout_window_minutes: minutes });
  }
  async function chooseLimit(limit: OptionalLimit, input: HTMLInputElement): Promise<void> {
    const stored = swarmSettings[limit.key];
    const text = input.value.trim();
    if (text === '') {
      if (stored !== null) await save({ [limit.key]: null });
      return;
    }
    const value = Number(text);
    if (!Number.isFinite(value) || (limit.whole && !Number.isInteger(value)) || value < limit.min || value > limit.max) {
      input.value = stored === null ? '' : String(stored);
      return;
    }
    if (value !== stored) await save({ [limit.key]: value });
  }
  const OPTIONS: Record<(typeof rows)[number], () => readonly string[]> = {
    page_default_view: () => PAGE_VIEWS,
    panel_default_density: () => PANEL_DENSITIES,
    character_pack: swarmChoices,
    upper_ranks_permissions: () => UPPER_POSTURES,
  };

  function words(row: (typeof rows)[number], value: string): string {
    if (row === 'upper_ranks_permissions') return t(`cplug.huddle.swarm.settings.upper.${value}`);
    if (row === 'character_pack') {
      if (value === FOLLOW_THEME) return t('cplug.huddle.swarm.settings.pack_theme');
      const named = t(`cplug.huddle.swarm.settings.pack.${value}`);
      return named.startsWith('cplug.') ? value : named;
    }
    return t(`cplug.huddle.swarm.settings.${row === 'page_default_view' ? 'view' : 'density'}.${value}`);
  }

  async function save(change: SwarmSettingsChange): Promise<void> {
    busy = true;
    failed = !(await saveSwarmSettings(change));
    busy = false;
  }

  function choose(row: (typeof rows)[number], value: string): Promise<void> {
    return save({ [row]: value } as Partial<SwarmPageSettings>);
  }

  const SAMPLE: Record<LookRank, ColorMember> = {
    sysop: { id: 1, companyId: null, sysop: true, base: true },
    company: { id: 2, companyId: 1, base: true },
    project: { id: 3, companyId: 1, projectId: 1, base: true },
    agent: { id: 4, companyId: 1, projectId: 1 },
  };
  const wheel = $derived(placeFamilies([{ id: 1 }], [1], swarmGround.ground));
  const sampleColor = (rank: LookRank) => colorOfMember(SAMPLE[rank], wheel, swarmLook.color_mode === 'random' ? byRandom : byProject);
  const animationOf = (state: CharacterState): string => swarmLook.animations[state] ?? STATES[state].animation;
  function animationWords(animation: string): string {
    if (animation === NO_ANIMATION) return t('cplug.huddle.swarm.settings.look.still');
    const owner = ALL_STATES.find((s) => STATES[s].animation === animation)!;
    return t(`cplug.huddle.swarm.state.${owner}`);
  }
</script>

<div class="pkg-set" data-swarm-settings>
  {#each rows as row (row)}
    <div class="pkg-set-row" data-swarm-setting={row}>
      <div class="pkg-set-text">
        <label class="pkg-set-label" for={`swarm-setting-${row}`}>{t(`cplug.huddle.swarm.settings.${row}`)}</label>
        <p class="pkg-set-hint">{t(`cplug.huddle.swarm.settings.${row}_help`)}</p>
      </div>
      <select id={`swarm-setting-${row}`} class="oc-field pkg-set-control" disabled={busy} value={swarmSettings[row]}
              onchange={(event) => void choose(row, (event.currentTarget as HTMLSelectElement).value)}>
        {#each OPTIONS[row]() as value (value)}
          <option {value}>{words(row, value)}</option>
        {/each}
      </select>
    </div>
  {/each}
  <div class="pkg-set-row" data-swarm-setting="closeout_window_minutes">
    <div class="pkg-set-text">
      <label class="pkg-set-label" for="swarm-setting-closeout_window_minutes">{t('cplug.huddle.swarm.settings.closeout_window_minutes')}</label>
      <p class="pkg-set-hint">{t('cplug.huddle.swarm.settings.closeout_window_minutes_help')}</p>
    </div>
    <input id="swarm-setting-closeout_window_minutes" class="oc-field pkg-set-control" type="number" inputmode="numeric"
           min={CLOSEOUT_MIN} max={CLOSEOUT_MAX} step="1" disabled={busy} value={swarmSettings.closeout_window_minutes}
           onchange={(event) => void chooseCloseout(event.currentTarget as HTMLInputElement)} />
  </div>
  {#each OPTIONAL_LIMITS as limit (limit.key)}
    <div class="pkg-set-row" data-swarm-setting={limit.key}>
      <div class="pkg-set-text">
        <label class="pkg-set-label" for={`swarm-setting-${limit.key}`}>{t(`cplug.huddle.swarm.settings.${limit.key}`)}</label>
        <p class="pkg-set-hint">{t(`cplug.huddle.swarm.settings.${limit.key}_help`)}</p>
      </div>
      <input id={`swarm-setting-${limit.key}`} class="oc-field pkg-set-control" type="number" inputmode="decimal" min={limit.min}
             max={limit.max} step={limit.step} disabled={busy} value={swarmSettings[limit.key] ?? ''}
             placeholder={t(`cplug.huddle.swarm.settings.${limit.key}_unset`)}
             onchange={(event) => void chooseLimit(limit, event.currentTarget as HTMLInputElement)} />
    </div>
  {/each}
  <section class="pkg-look" data-swarm-look aria-labelledby="swarm-look-title">
    <h3 class="pkg-look-title" id="swarm-look-title">{t('cplug.huddle.swarm.settings.look.title')}</h3>
    <div class="pkg-set-row" data-swarm-setting="color_mode">
      <div class="pkg-set-text">
        <label class="pkg-set-label" for="swarm-setting-color_mode">{t('cplug.huddle.swarm.settings.look.color_mode')}</label>
        <p class="pkg-set-hint">{t('cplug.huddle.swarm.settings.look.color_mode_help')}</p>
      </div>
      <select id="swarm-setting-color_mode" class="oc-field pkg-set-control" disabled={busy} value={swarmLook.color_mode}
              onchange={(event) => void save({ color_mode: (event.currentTarget as HTMLSelectElement).value as (typeof COLOR_MODES)[number] })}>
        {#each COLOR_MODES as mode (mode)}<option value={mode}>{t(`cplug.huddle.swarm.settings.look.mode.${mode}`)}</option>{/each}
      </select>
    </div>
    {#each LOOK_RANKS as rank (rank)}
      <div class="pkg-set-row" data-swarm-setting={`shape-${rank}`}>
        <span class="pkg-look-figure" data-swarm-look-preview={rank}>
          <Character state="idle" size={32} shape={HOME_SHAPES[swarmLook.shapes[rank]]} color={sampleColor(rank)}
                     label={t(`cplug.huddle.swarm.settings.look.rank.${rank}`)} />
        </span>
        <div class="pkg-set-text">
          <label class="pkg-set-label" for={`swarm-setting-shape-${rank}`}>{t(`cplug.huddle.swarm.settings.look.rank.${rank}`)}</label>
        </div>
        <select id={`swarm-setting-shape-${rank}`} class="oc-field pkg-set-control" disabled={busy} value={swarmLook.shapes[rank]}
                onchange={(event) => void save({ shapes: { [rank]: (event.currentTarget as HTMLSelectElement).value } as SwarmSettingsChange['shapes'] })}>
          {#each SHAPE_NAMES as shape (shape)}<option value={shape}>{t(`cplug.huddle.swarm.settings.look.shape.${shape}`)}</option>{/each}
        </select>
      </div>
    {/each}
    <p class="pkg-set-hint pkg-look-note">{t('cplug.huddle.swarm.settings.look.animations_help')}</p>
    {#each ALL_STATES as state (state)}
      <div class="pkg-set-row" data-swarm-setting={`animation-${state}`}>
        <span class="pkg-look-figure" data-swarm-look-preview={state}><Character {state} size={24} seed="look" /></span>
        <div class="pkg-set-text">
          <label class="pkg-set-label" for={`swarm-setting-animation-${state}`}>{t(`cplug.huddle.swarm.state.${state}`)}</label>
        </div>
        <select id={`swarm-setting-animation-${state}`} class="oc-field pkg-set-control" disabled={busy} value={animationOf(state)}
                onchange={(event) => void save({ animations: { [state]: (event.currentTarget as HTMLSelectElement).value } })}>
          {#each [...new Set(ANIMATIONS), NO_ANIMATION] as animation (animation)}
            <option value={animation}>{animationWords(animation)}</option>
          {/each}
        </select>
      </div>
    {/each}
    
    <div class="pkg-set-row" data-swarm-setting="naming_family">
      <div class="pkg-set-text">
        <span class="pkg-set-label" id="swarm-setting-naming_family">{t('cplug.huddle.swarm.settings.naming_family')}</span>
        <p class="pkg-set-hint">{t('cplug.huddle.swarm.settings.naming_family_help')}</p>
      </div>
      <Check label="" bare role="switch" checked={swarmSettings.naming_family} disabled={busy}
             ariaLabel={t('cplug.huddle.swarm.settings.naming_family')} onToggle={(next) => void save({ naming_family: next })} />
    </div>
    
    <div class="pkg-set-row" data-swarm-setting="chat_card_bodies">
      <div class="pkg-set-text">
        <span class="pkg-set-label" id="swarm-setting-chat_card_bodies">{t('cplug.huddle.swarm.settings.chat_card_bodies')}</span>
        <p class="pkg-set-hint">{t('cplug.huddle.swarm.settings.chat_card_bodies_help')}</p>
      </div>
      <Check label="" bare role="switch" checked={swarmSettings.chat_card_bodies} disabled={busy}
             ariaLabel={t('cplug.huddle.swarm.settings.chat_card_bodies')} onToggle={(next) => void save({ chat_card_bodies: next })} />
    </div>
  </section>
  {#if failed}<p class="pkg-set-error" role="alert" data-swarm-settings-failed>{t('cplug.huddle.swarm.settings.failed')}</p>{/if}
</div>

<style>
  @layer components {
    .pkg-set {
      font-family: var(--font-mono);
      min-width: 0;
    }

    .pkg-set-row {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 12px 0;
      border-bottom: var(--oc-border, 1px) solid var(--oc-line-rule);
    }

    .pkg-set-text {
      flex: 1 1 240px;
      min-width: 0;
    }

    .pkg-set-label {
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
    }

    .pkg-set-hint {
      margin: 4px 0 0;
      color: var(--oc-text-dim);
      font-size: var(--oc-fs-micro);
    }

    .pkg-set-control {
      flex: none;
      width: 14em;
    }

    .pkg-look {
      margin-top: var(--oc-space-4, 16px);
    }

    .pkg-look-title {
      margin: 0;
      padding: 8px 0;
      color: var(--oc-text-secondary);
      font-size: var(--oc-fs-label);
      font-weight: normal;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      box-shadow: inset 0 calc(-1 * var(--oc-border, 1px)) 0 var(--oc-line-rule);
    }

    .pkg-look-figure {
      display: inline-flex;
      flex: none;
      align-items: center;
      justify-content: center;
      width: 40px;
    }

    .pkg-look-note {
      padding-top: 12px;
    }

    .pkg-set-error {
      margin: var(--oc-space-2) 0 0;
      color: var(--oc-coral);
      font-size: var(--oc-fs-label);
    }
  }
</style>
