<script lang="ts">
  /* Escape closes it session skills */
  import { onMount } from 'svelte';
  import '../subagents/popup-list.css';
  import './session-skills.css';
  import { t } from '../i18n/index.svelte';
  import { subscribe } from '../../opscenter/api/events.svelte';
  import { agoText, emptyMessage, fetchSkillFires, type SessionSkillFires } from '../skill-fires/skill-fires';
  import { fetchSessionSkills, putOverride, refusalOf } from '../skills-page/skills-api';
  import { CLAUDE_STATE_KEYS } from '../skills-page/skills-model';
  import type { SessionSkill, SessionSkills } from '../skills-page/skills-types';
  import { isOn, stateFor, switchTarget } from './session-skills';
  import ScoutSection from './ScoutSection.svelte';

  import { takeDrawerFocus } from './drawer.svelte';

  let {
    sessionId,
    slot,
    full = false,
    onClose,
  }: {
    sessionId: string;
    slot: string;
    full?: boolean;
    onClose: () => void;
  } = $props();

  let payload = $state<SessionSkills | null>(null);
  let fires = $state<SessionSkillFires | null>(null);
  let failure = $state<string | null>(null);
  let toggleError = $state<string | null>(null);
  let busy = $state<string | null>(null);
  let restart = $state(false);
  let applied = $state(false);
  let panel = $state<HTMLElement | null>(null);
  const nowMs = Date.now();
  let lastOwn = 0;

  const skills = $derived(payload?.state === 'ok' ? (payload.skills ?? []) : []);
  const family = $derived(payload?.family ?? '');
  const workingDir = $derived(payload?.working_dir ?? null);
  const firesEmpty = $derived(fires ? emptyMessage(fires) : null);

  async function load(): Promise<void> {
    try {
      payload = await fetchSessionSkills(sessionId);
      failure = null;
    } catch (err: unknown) {
      failure = t('skills.session.failed', { reason: refusalOf(err, '') });
    }
  }

  onMount(() => {
    let live = true;
    void load();
    fetchSkillFires(sessionId)
      .then((body) => {
        if (live) fires = body;
      })
      .catch(() => {
      });
    const stop = subscribe('skills.changed', () => {
      if (Date.now() - lastOwn > 1500) void load();
    });
    return () => {
      live = false;
      stop();
    };
  });

  async function toggle(skill: SessionSkill, on: boolean): Promise<void> {
    const target = switchTarget(skill, family, workingDir);
    if (!target || busy) return;
    const state = stateFor(skill, target, on);
    toggleError = null;
    if (state === undefined) return;
    busy = skill.name;
    lastOwn = Date.now();
    try {
      const result = await putOverride({
        harness: target.harness,
        file: target.file,
        skill: skill.name,
        state,
        projectPath: target.projectPath,
      });
      lastOwn = Date.now();
      if (result.wrote) {
        applied = true;
        restart = restart || result.restart_required;
      }
      await load();
    } catch (err: unknown) {
      toggleError = t('skills.session.toggle_failed', { name: skill.name, reason: refusalOf(err, '') });
    } finally {
      busy = null;
    }
  }

  function stateWord(skill: SessionSkill): string {
    if (skill.shadowed_by) return t('skills.session.shadowed');
    return t(CLAUDE_STATE_KEYS[skill.state] ?? 'skills.state.on');
  }

  onMount(() => {
    if (takeDrawerFocus(slot)) panel?.focus();
  });

  function close(): void {
    onClose();
  }

  function onKeydown(event: KeyboardEvent): void {
    if (event.key !== 'Escape') return;
    event.preventDefault();
    event.stopPropagation();
    close();
  }
</script>

<div
  class="sal-panel sal-panel--docked"
  class:sal-panel--full={full}
  role="dialog"
  aria-modal="false"
  aria-label={t('skills.session.label')}
  tabindex="-1"
  bind:this={panel}
  onkeydown={onKeydown}
  data-session-skills
>
  <header class="sal-titlebar">
    <h2 class="sal-title">{t('skills.session.title')}</h2>
    <span class="sal-name">{workingDir ? t('skills.session.folder', { dir: workingDir }) : ''}</span>
    <button type="button" class="sal-close" onclick={close}>{t('skills.session.close')}</button>
  </header>

  {#if failure}
    <p class="sal-note" role="status">{failure}</p>
  {:else if payload === null}
    <p class="sal-note" role="status">{t('skills.session.loading')}</p>
  {:else if payload.state === 'unsupported'}
    <p class="sal-note" data-session-skills-unsupported>{t('skills.session.unsupported')}</p>
  {:else}
    <p class="sal-summary" data-session-skills-summary>
      {t('skills.session.summary', { count: skills.length, tokens: payload.budget_tokens_est ?? 0 })}
    </p>
    {#if skills.length === 0}
      <p class="sal-note">{t('skills.session.empty')}</p>
    {:else}
      <table class="sal-table sal-table--skills">
        <thead>
          <tr>
            <th scope="col">{t('skills.session.col.skill')}</th>
            <th scope="col">{t('skills.session.col.state')}</th>
            <th scope="col" class="sal-num">{t('skills.session.col.cost')}</th>
            <th scope="col"></th>
          </tr>
        </thead>
        <tbody>
          {#each skills as skill (skill.location_id)}
            {@const target = switchTarget(skill, family, workingDir)}
            <tr class:sal-row--unseen={!skill.model_sees} data-session-skill={skill.name}>
              <td class="sal-type">{skill.name}</td>
              <td>{stateWord(skill)}</td>
              <td class="sal-num">{skill.tokens_est}</td>
              <td>
                {#if target}
                  <button
                    type="button"
                    class="sal-close"
                    role="switch"
                    aria-checked={isOn(skill)}
                    aria-label={t('manager.toggle.label', { name: skill.name })}
                    data-session-skill-switch={skill.name}
                    disabled={busy !== null}
                    onclick={() => void toggle(skill, !isOn(skill))}
                    >{busy === skill.name ? t('manager.toggle.working') : isOn(skill) ? t('manager.toggle.on') : t('manager.toggle.off')}</button
                  >
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
    {#if skills.some((s) => switchTarget(s, family, workingDir))}
      <p class="sal-note" data-session-skills-writes>
        {t(family === 'codex' ? 'skills.session.writes_codex' : 'skills.session.writes_claude')}
      </p>
    {/if}
    {#if skills.some((s) => s.scope === 'plugin' || s.scope === 'system')}
      <p class="sal-note">{t('skills.session.no_switch')}</p>
    {/if}
    {#if toggleError}<p class="sal-error" role="alert" data-session-skills-error>{toggleError}</p>{/if}
    {#if applied}
      <p class="sal-note" role="status" data-session-skills-hint>
        {restart || payload.restart_required ? t('skills.session.restart') : t('skills.session.applied')}
        {#if payload.reload_hint}{t('skills.session.reload', { hint: payload.reload_hint })}{/if}
      </p>
    {:else if payload.reload_hint}
      <p class="sal-note" data-session-skills-hint>{t('skills.session.reload', { hint: payload.reload_hint })}</p>
    {/if}

    {#if family === 'claude'}<ScoutSection {sessionId} {workingDir} />{/if}

    <h3 class="sal-section">{t('skills.session.fires')}</h3>
    {#if fires === null}
      <p class="sal-note">{t('skills.list.loading')}</p>
    {:else if firesEmpty}
      <p class="sal-note" data-skill-fires-empty={fires.state}>{firesEmpty}</p>
    {:else}
      <table class="sal-table">
        <thead>
          <tr>
            <th scope="col">{t('skills.list.col.skill')}</th>
            <th scope="col">{t('skills.list.col.how')}</th>
            <th scope="col" class="sal-num">{t('skills.list.col.when')}</th>
          </tr>
        </thead>
        <tbody>
          {#each fires.recent as row, i (i)}
            <tr data-skill-fire-source={row.source}>
              <td class="sal-type">{row.skill}</td>
              <td>{t(`skills.source.${row.source}`)}</td>
              <td class="sal-num">{agoText(row.at, nowMs) ?? ''}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    {/if}
  {/if}
</div>
