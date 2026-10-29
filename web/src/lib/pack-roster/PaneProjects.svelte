
<script lang="ts">
  import Button from '../base/Button.svelte';
  import { t } from '../i18n/index.svelte';
  import { sessions } from '../../opscenter/api/sessions.svelte';
  import { projects } from '../../opscenter/api/projects.svelte';
  import { openSession } from '../../opscenter/api/host';
  import { projectColorVar, isProjectColor } from '../project-colors/palette';
  import Icon from '../../opscenter/ui/Icon.svelte';
  import { rosterUi } from './roster-ui.svelte';
  import type { RosterComputer } from './roster-model';

  const { c }: { c: RosterComputer } = $props();
  const mine = $derived((sessions.data ?? []).filter((s) => (c.isSelf ? !s.host_key || c.hostKeys.includes(s.host_key) : s.host_key !== undefined && c.hostKeys.includes(s.host_key))));
  const groups = $derived.by(() => {
    const by = new Map<string, { name: string; color: string | null; rows: typeof mine }>();
    for (const s of mine) {
      const name = s.project_name ?? t('roster.proj.unsorted');
      const color = projects.data?.find((p) => p.id === s.project_id)?.color ?? null;
      const g = by.get(name) ?? { name, color: isProjectColor(color) ? color : null, rows: [] };
      g.rows.push(s);
      by.set(name, g);
    }
    return [...by.values()].sort((a, b) => a.name.localeCompare(b.name));
  });
  const isLive = (state: string | null): boolean => state === 'working' || state === 'question';
  const countWords = (n: number): string => (n === 1 ? t('roster.proj.sessions_one') : t('roster.proj.sessions_other', { count: n }));
  const foldKey = (name: string): string => `${c.id}/${name}`;
  const fold = (name: string): void => { rosterUi.fold[foldKey(name)] = !rosterUi.fold[foldKey(name)]; };
</script>

{#if groups.length === 0}
  <section class="m1-sec"><h3 class="pp-k">{t('roster.proj.none_title')}</h3>
    <p class="pp-hint">{c.kind === 'ssh-only' ? t('roster.proj.ssh_none') : t('roster.proj.none', { name: c.name })}</p></section>
{:else}
  <section class="m1-sec">
    <h3 class="pp-k">{groups.length === 1 ? t('roster.proj.head_one', { sessions: countWords(mine.length) }) : t('roster.proj.head_other', { count: groups.length, sessions: countWords(mine.length) })}</h3>
    <div class="m1-projs">
      {#each groups as g (g.name)}
        {@const folded = !!rosterUi.fold[foldKey(g.name)]}
        {@const live = g.rows.filter((s) => isLive(s.activity_status)).length}
        <section class="m1-proj" data-project={g.name} data-folded={folded ? '' : null} data-block={g.color ? '' : null} style={g.color ? `--sp-block: ${projectColorVar(g.color)}` : undefined}>
          <Button variant="row" data-proj-head aria-expanded={!folded} onclick={() => fold(g.name)}>
            <span class="m1-proj__chev" aria-hidden="true"><Icon name="chevron-down" size={12} /></span>
            <span class="m1-proj__name">{g.name}</span>
            <span class="m1-proj__n">{live ? t('roster.proj.live', { base: countWords(g.rows.length), count: live }) : countWords(g.rows.length)}</span>
          </Button>
          <ul class="m1-proj__rows" hidden={folded}>
            {#each g.rows as s (s.session.id)}
              {@const name = s.label ?? s.tmux_session ?? s.session.id}
              <li class="m1-ses">
                <i class="rs-led" data-s={s.activity_status === 'working' ? 'g' : s.activity_status === 'question' ? 'y' : 'n'}></i>
                <span class="m1-ses__name">{name}</span>
                <Button size="sm" aria-label={t('roster.proj.open_aria', { name })} onclick={() => openSession(s.session.id, s.tmux_session)}>{t('roster.proj.open')}</Button>
              </li>
            {/each}
          </ul>
        </section>
      {/each}
    </div>
  </section>
{/if}
