<script lang="ts">
  import '../../lib/ledger/ledger-chrome.css';
  import AskForm from '../../lib/approvals/AskForm.svelte';
  import type { ApprovalItem } from '../../lib/approvals/approvals-model';

  const item: ApprovalItem = {
    id: 'sg-ask', source: 'dialog', host: 'local', session_id: 'sg-ses', session_name: 'billing api', project: 'billing',
    kind: 'ask_user_question', questions_state: 'matched', questions_fingerprint: 'sg'.repeat(32),
    questions: [
      { header: 'Database', question: 'Which database should the billing api use?', multi_select: false, options: [
        { label: 'Postgres', description: 'the one the team already runs' },
        { label: 'SQLite', description: 'a single file, no server to keep up' }] },
      { header: 'Checks', question: 'Which checks should run before a deploy?', multi_select: true, options: [
        { label: 'Unit tests', description: 'fast, run on every push' },
        { label: 'Type check', description: 'catches the quiet breakage' },
        { label: 'Load test', description: 'slow, only before a release' }] },
      { header: 'Layout', question: 'Which layout for the invoice page?', multi_select: false, options: [
        { label: 'List', description: 'dense rows', preview: 'invoice 1042   paid\ninvoice 1043   due' },
        { label: 'Grid', description: 'cards', preview: '[ 1042 ] [ 1043 ]\n[ paid ] [ due  ]' }] },
    ],
  } as ApprovalItem;
</script>

<div class="pledger sg-ask"><AskForm {item} onJump={() => {}} /></div>

<style>
  @layer components {
    .sg-ask { max-width: 760px; box-shadow: inset 0 0 0 var(--oc-border, 1px) var(--oc-line-rule); }
  }
</style>
