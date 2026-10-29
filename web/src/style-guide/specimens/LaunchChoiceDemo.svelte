<script lang="ts">
  import LaunchChoice from '../../lib/launch-picker/LaunchChoice.svelte';
  import { rowsFromProfiles } from '../../lib/launch-picker/picker-model';
  import type { ProfileRow } from '../../lib/launch-profiles-page/api';
  import { t } from '../../lib/i18n/index.svelte';

  interface Props { part?: 'profile' | 'full' }
  const { part = 'full' }: Props = $props();

  const profile = (id: string, harness: string, isDefault: boolean, permissions = 'harness_default'): ProfileRow => ({
    id, harness, label: id, icon: null, description: null, default: isDefault,
    account: { mode: 'follow_active', account_id: null }, endpoint: { mode: 'native', connection_id: null },
    model: { mode: 'default', value: null }, permissions, flags: [], env: [], secrets: [], shell_profile: true, before_launch: null,
    custom_command: null, custom_command_ack_no_args: false,
    summary: { permissions_badge: permissions === 'skip_all' ? 'skips all permission checks' : 'default permissions', model: 'default', account: 'follow_active', endpoint: 'native' },
  }) as unknown as ProfileRow;

  const rows = rowsFromProfiles(
    [profile('claude', 'claude', true), profile('claude-yolo', 'claude', false, 'skip_all'), profile('codex', 'codex', true)],
    [],
    { followActive: t('launch_profiles.list.follow'), modelDefault: t('launch_picker.model_default'), modelAsk: t('launch_picker.model_ask') },
  );
  const accounts = { options: [{ id: 'work', name: 'work' }, { id: 'play', name: 'play' }], selected_id: 'work', pinned: false };
  let value = $state('claude');
</script>

<div style="max-width: 28rem">
  <LaunchChoice {rows} bind:value accounts={part === 'full' ? accounts : null} followWords={t('launch_profiles.list.follow')} />
</div>
