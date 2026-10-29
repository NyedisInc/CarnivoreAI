<script lang="ts">
  import ApprovalCard from '../../lib/approvals/ApprovalCard.svelte';
  import { rememberFolded } from '../../lib/approvals/card-fold';
  import type { ApprovalItem } from '../../lib/approvals/approvals-model';

  const AGO = Date.now() / 1000;

  const SAMPLES: ApprovalItem[] = [
    {
      id: 'sg-qc-trust', source: 'dialog', host: 'local', session_id: 'sg-1', session_name: 'omega', project: 'harbor',
      family: 'claude', kind: 'folder_trust', startup_kind: 'trust', created_at: AGO - 360,
      question: 'Quick safety check: Is this a project you created or one you trust?',
      body: 'update the onboarding checklist',
      rows: [{ label: 'No, exit', role: 'option' }, { label: 'Yes, I trust this folder', role: 'option' }],
    },
    {
      id: 'sg-qc-bash', source: 'dialog', host: 'local', session_id: 'sg-2', session_name: 'atlas-api', project: 'billing service',
      family: 'claude', kind: 'permission', plain_yes: 'Yes', plain_no: 'No', created_at: AGO - 38,
      question: 'Do you want to proceed?', summary: 'Bash command: rm -rf build && npm run build',
      body: ' Bash command\n\n   rm -rf build && npm run build\n\n Do you want to proceed?\n ❯ 1. Yes\n   2. No',
      rows: [{ label: 'Yes', role: 'option' }, { label: "Yes, and don't ask again for rm commands", role: 'option' }, { label: 'No', role: 'option' }],
    },
    {
      id: 'sg-qc-edit', source: 'dialog', host: 'local', session_id: 'sg-2', session_name: 'atlas-api', project: 'billing service',
      family: 'claude', kind: 'permission', plain_yes: 'Yes', plain_no: 'No', created_at: AGO - 60,
      question: 'Do you want to make this edit?', summary: 'Edit file: src/billing/retry_policy.py',
      body: ' Edit file\n   src/billing/retry_policy.py\n   - MAX_RETRIES = 3\n   + MAX_RETRIES = 5\n Do you want to make this edit?\n ❯ 1. Yes\n   2. No',
      rows: [{ label: 'Yes', role: 'option' }, { label: 'No', role: 'option' }],
    },
    {
      id: 'sg-qc-ask', source: 'dialog', host: 'local', session_id: 'sg-3', session_name: 'nova', project: 'carnivore',
      family: 'claude', kind: 'ask_user_question', created_at: AGO - 180, question: 'which screens should the new card layout cover first?',
      rows: [{ label: 'questions tab only', role: 'option', description: 'smallest change, ships today' }, { label: 'questions tab and the inbox', role: 'option', description: 'same card in both places' }],
    },
    {
      id: 'sg-qc-plan', source: 'dialog', host: 'local', session_id: 'sg-4', session_name: 'vega', project: 'carnivore',
      family: 'claude', kind: 'plan_approval', created_at: AGO - 540, question: 'Would you like to proceed?',
      body: 'Plan: split approvals store\n1. Extract the model\n2. Move the store\n3. Update every import\n4. Tests\n5. Docs',
      rows: [{ label: 'Yes, manually approve edits', role: 'option' }, { label: 'Tell Claude what to change', role: 'option' }],
    },
    {
      id: 'sg-qc-codex', source: 'dialog', host: 'local', session_id: 'sg-5', session_name: 'sage', project: 'hosted site',
      family: 'codex', kind: 'codex_approval', plain_yes: 'Yes, proceed (y)', created_at: AGO - 120,
      question: 'Would you like to run the following command?', summary: 'command: pip install -r requirements.txt',
      body: 'Would you like to run the following command?\nReason: needs network to download packages\n$ pip install -r requirements.txt',
      rows: [{ label: 'Yes, proceed (y)', role: 'option' }, { label: 'No, and tell Codex what to do differently (esc)', role: 'option' }],
    },
    {
      id: 'sg-qc-readonly', source: 'startup_prompt', host: 'local', session_id: 'sg-6', session_name: 'orion', project: 'ops tools',
      kind: 'resume_picker', created_at: AGO - 660, body: 'Resume Session\n  search...\n  1. yesterday, fix the build',
    },
  ];

  for (const item of SAMPLES.slice(2)) rememberFolded(item.id, true);
</script>

<div class="pledger sg-qc">
  {#each SAMPLES as item (item.id)}
    <ApprovalCard {item} onJump={() => {}} foldable age="waiting" />
  {/each}
</div>

<style>
  @layer components {
    .sg-qc {
      display: flex;
      flex-direction: column;
      gap: var(--oc-space-2);
      max-width: 380px;
    }
  }
</style>
