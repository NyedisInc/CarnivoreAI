
<script lang="ts">
  import { t } from '../i18n/index.svelte';
  import type { ModsResponse } from './mods-api';
  import { groupProblems } from './mods-format';

  let { list, notice }: { list: ModsResponse | null; notice: string } = $props();

  const locked = $derived(list?.accounts.status === 'accounts_unreadable');
  const problems = $derived(groupProblems(list?.groups ?? []));
</script>

{#if list && !list.claude.ok}
  <p class="mods-line mods-line--warn" role="status" data-mods-claude-old>{t('mods.page.claude_too_old', { version: list.claude.version ?? '?' })}</p>
{/if}
{#if locked}
  <p class="mods-line mods-line--error" role="alert" data-mods-locked>{t('mods.page.accounts_unreadable')}</p>
{/if}
{#each problems as problem (problem)}
  <p class="mods-line mods-line--warn" role="status" data-mods-problem>{problem}</p>
{/each}
{#if notice}<p class="mods-line mods-line--notice" role="status" data-mods-notice>{notice}</p>{/if}
