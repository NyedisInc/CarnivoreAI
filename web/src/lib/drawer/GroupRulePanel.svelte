
<script lang="ts">
    import { onMount } from 'svelte';
    import Glyph from '../Glyph.svelte';
    import IconButton from '../base/IconButton.svelte';
    import Field from '../base/Field.svelte';
    import { t } from '../i18n/index.svelte';
    import * as GroupStore from './group-store';
    import { RULE_FLAGS, type GroupRule, type RuleFlag } from './group-rule';

    const GLYPH: Record<RuleFlag, string> = {
        running: 'bolt', sleeping: 'sleeping-agent', coffee: 'coffee', sharing: 'telescope', pinned: 'pin',
        remote: 'globe', swarm: 'users', unread: 'envelope-filled', waiting: 'bell',
    };

    interface Props {
        groupUuid: string;
        save: (rule: GroupRule) => Promise<boolean>;
    }
    let { groupUuid, save }: Props = $props();

    // svelte-ignore state_referenced_locally
    const start = GroupStore.groupByUuid(groupUuid)?.rule ?? null;
    let flags = $state<RuleFlag[]>(start ? [...start.flags] : []);
    let prefix = $state(start?.prefix ?? '');
    let suffix = $state(start?.suffix ?? '');
    let tick = $state(0);

    const rule = $derived<GroupRule>({ flags, prefix: prefix.trim(), suffix: suffix.trim() });
    const empty = $derived(flags.length === 0 && !rule.prefix && !rule.suffix);
    const count = $derived.by(() => (tick >= 0 && !empty ? GroupStore.countMatching(rule) : 0));

    onMount(() => GroupStore.subscribeRows(() => { tick += 1; }));

    function toggle(flag: RuleFlag): void {
        flags = flags.includes(flag) ? flags.filter((f) => f !== flag) : RULE_FLAGS.filter((f) => f === flag || flags.includes(f));
        void save(rule);
    }
    function commit(): void {
        void save(rule);
    }
</script>

<div class="grp-rule">
  <div class="grp-rule__icons" role="group" aria-label={t('sidebar.group.rule.title')}>
    {#each RULE_FLAGS as flag (flag)}
      <IconButton
        label={t(`sidebar.group.rule.${flag}`)}
        pressed={flags.includes(flag)}
        onclick={() => toggle(flag)}
      ><Glyph name={GLYPH[flag]} /></IconButton>
    {/each}
  </div>
  <div class="grp-rule__fields">
    <Field label={t('sidebar.group.rule.prefix')} maxlength={64} bind:value={prefix} onchange={commit}
      onkeydown={(e) => { if (e.key === 'Enter') commit(); }} />
    <Field label={t('sidebar.group.rule.suffix')} maxlength={64} bind:value={suffix} onchange={commit}
      onkeydown={(e) => { if (e.key === 'Enter') commit(); }} />
  </div>
  <div class="grp-rule__count" aria-live="polite">{empty ? t('sidebar.group.rule.empty') : t('sidebar.group.rule.count', { count })}</div>
</div>

<style>
  @layer components {
    .grp-rule { display: flex; flex-direction: column; gap: var(--oc-space-2); padding: var(--oc-space-2) var(--oc-space-3); min-width: 0; font-family: var(--font-mono, ui-monospace, monospace); }
    .grp-rule__icons { display: flex; flex-wrap: wrap; gap: var(--oc-space-1); }
    .grp-rule__fields { display: flex; flex-wrap: wrap; gap: var(--oc-space-2); }
    .grp-rule__fields > :global(*) { flex: 1 1 6rem; min-width: 0; }
    .grp-rule__count { font-size: var(--oc-fs-hint); color: var(--oc-text-secondary); }
  }
</style>
