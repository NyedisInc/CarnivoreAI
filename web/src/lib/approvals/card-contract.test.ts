import { describe, expect, test } from 'vitest';
import { setLocale } from '../i18n/index.svelte';
import {
  ASK_REVIEW_QUESTION, MAX_FACTS, askReviewKey, beastWouldAnswer, cardContract, cardOptionTone, factText, foldKey, midCut, optionWords, say,
  type CardContract, type ListingRowLike,
} from './card-contract';
import type { ApprovalItem } from './approvals-model';

setLocale('en');

const FOLDER = '/Users/me/Library/Mobile Documents/com~apple~CloudDocs/work/Org/Example/app/tooling/catalog';
const ROWS: ListingRowLike[] = [
  { label: 'omega', tmux_session: 'carnivore_omega', session: { id: 'ses_1', tmux_session: 'carnivore_omega', working_dir: FOLDER } },
  { label: 'nova', tmux_session: 'carnivore_nova', session: { id: 'ses_2', tmux_session: 'carnivore_nova', working_dir: '/tmp/work' } },
];

const TRUST_TEXT = 'Accessing workspace:\n\n' + FOLDER + '\n\nQuick safety check: Is this a project you created or one you trust?';

const TRUST: ApprovalItem = {
  id: 'dlg:ses_1:ab', source: 'dialog', host: 'local', session_id: 'ses_1', session_name: 'omega', project: 'storefront',
  family: 'claude', kind: 'folder_trust', startup_kind: 'trust', fingerprint: 'a'.repeat(64),
  question: 'Quick safety check: Is this a project you created or one you trust?', body: TRUST_TEXT,
  rows: [{ label: 'No, exit', role: 'option' }, { label: 'Yes, I trust this folder', role: 'option' }],
};

const BASH: ApprovalItem = {
  id: 'dlg:ses_2:cd', source: 'dialog', host: 'local', session_id: 'ses_2', session_name: 'nova', project: 'billing',
  family: 'claude', kind: 'permission', question: 'Do you want to proceed?', plain_yes: 'Yes', plain_no: 'No',
  summary: 'Bash command: rm -rf build && npm run build',
  body: ' Bash command\n\n   rm -rf build && npm run build\n\n Do you want to proceed?\n ❯ 1. Yes\n   2. No',
  rows: [{ label: 'Yes', role: 'option' }, { label: 'No', role: 'option' }],
};

function facts(card: CardContract): Record<string, string> {
  return Object.fromEntries(card.facts.map((fact) => [fact.id, factText(fact)]));
}

describe('a startup screen with buttons (folder trust)', () => {
  const card = cardContract(TRUST, { rows: ROWS });

  test('says what is asked in our words, once, and never repeats claude\'s sentence', () => {
    expect(card.kind).toBe('startup');
    expect(card.tone).toBe('startup');
    expect(card.who).toBe('omega');
    expect(card.where).toBe('storefront');
    expect(say(card.headline)).toBe('omega wants to know if you trust this folder before claude reads or runs anything in it.');
    expect(say(card.headline)).not.toContain('Quick safety check');
  });

  test('facts are the folder from the listing (cut in the middle), what yes does and what no does', () => {
    expect(card.facts.map((f) => f.id)).toEqual(['folder', 'if_yes', 'if_no']);
    expect(card.facts[0]!.full).toBe(FOLDER);
    expect(factText(card.facts[0]!)).toContain('...');
    expect(factText(card.facts[0]!).endsWith('tooling/catalog')).toBe(true);
    expect(facts(card).if_yes).toBe('claude can read, edit and run code here');
    expect(facts(card).if_no).toBe('claude exits and the session stops');
  });

  test('the pane text is only the raw fold, and the chip says it always waits', () => {
    expect(card.raw).toEqual({ kind: 'text', text: TRUST_TEXT });
    expect(card.chip).toBe('waits');
  });

  test('a trust screen whose no does not quit has no "if no" fact, and no listing row means the screen fact', () => {
    const soft = cardContract({ ...TRUST, rows: [{ label: 'No, continue without these permissions', role: 'option' }, { label: 'Yes, I trust this folder', role: 'option' }] });
    expect(soft.facts.map((f) => f.id)).toEqual(['screen', 'if_yes']);
    expect(facts(soft).screen).toBe('folder trust');
  });

  test('another startup screen with its own words, and an unknown one with the generic line', () => {
    const mcp = cardContract({ ...TRUST, kind: 'other', startup_kind: 'mcp_server' }, { rows: ROWS });
    expect(say(mcp.headline)).toBe('omega found an mcp server set up for this folder and asks whether to use it.');
    expect(facts(mcp).if_yes).toBe('the server starts with this session');
    const odd = cardContract({ ...TRUST, kind: 'other', startup_kind: 'chrome_extension' });
    expect(say(odd.headline)).toBe('omega is stopped on a startup screen and needs a choice from you.');
    expect(facts(odd).screen).toBe('claude in chrome');
  });
});

describe('a startup screen with no buttons (startup_prompt)', () => {
  test('read only: the screen, why there are no buttons, the text under details', () => {
    const card = cardContract({ id: 'sp:1', source: 'startup_prompt', session_name: 'orion', kind: 'oauth_login', body: 'Select login method:' });
    expect(card.kind).toBe('startup');
    expect(card.tone).toBe('raw');
    expect(card.chip).toBe('read_only');
    expect(say(card.headline)).toBe('orion is stopped on a startup screen, so there are no buttons here.');
    expect(facts(card)).toEqual({ screen: 'sign in', why_none: 'it needs a browser sign-in or typing' });
    expect(card.raw).toEqual({ kind: 'text', text: 'Select login method:' });
  });
});

describe('a permission prompt', () => {
  test('bash: the command, where it runs and its risk; beast mode would answer it', () => {
    const card = cardContract(BASH, { rows: ROWS });
    expect(card.kind).toBe('bash');
    expect(card.tone).toBe('perm');
    expect(say(card.headline)).toBe('nova wants to run a command.');
    expect(facts(card)).toEqual({ command: 'rm -rf build && npm run build', runs_in: '/tmp/work', risk: 'delete' });
    expect(card.facts.find((f) => f.id === 'risk')?.tone).toBe('warn');
    expect(card.raw).toEqual({ kind: 'code', code: 'rm -rf build && npm run build' });
    expect(card.chip).toBe('beast');
  });

  test('a script of several lines says how many lines', () => {
    const card = cardContract({ ...BASH, summary: 'Bash command: ls', body: ' Bash command\n\n   ls\n   sudo ls /root\n\n Do you want to proceed?\n ❯ 1. Yes\n   2. No' });
    expect(say(card.headline)).toBe('nova wants to run a 2 line script.');
    expect(facts(card)).toEqual({ script: '2 lines', risk: 'sudo' });
  });

  test('edit: the file, cut in the middle when long', () => {
    const card = cardContract({ ...BASH, summary: 'Edit file: src/billing/retry_policy.py', body: ' Edit file\n   src/billing/retry_policy.py\n Do you want to make this edit?\n ❯ 1. Yes\n   2. No' });
    expect(card.kind).toBe('edit');
    expect(say(card.headline)).toBe('nova wants to change a file.');
    expect(facts(card).file).toBe('src/billing/retry_policy.py');
  });

  test('another tool names the tool; a prompt whose only yes is "Yes, and ..." waits for you', () => {
    const card = cardContract({ ...BASH, plain_yes: null, summary: null, body: ' Web fetch request\n   https://example.com\n Do you want to allow?\n ❯ 1. Yes, and don\'t ask again\n   2. No' });
    expect(card.kind).toBe('permission');
    expect(say(card.headline)).toBe('nova wants permission to use web fetch request.');
    expect(facts(card).tool).toBe('web fetch request');
    expect(card.chip).toBe('waits');
  });

  test('a summary that is only the question (no header above it) never becomes the headline or a tool fact', () => {
    const bare = { ...BASH, body: ' Do you want to proceed?\n ❯ 1. Yes\n   2. No', summary: 'Do you want to proceed?' };
    const card = cardContract(bare);
    expect(card.kind).toBe('permission');
    expect(card.headline).toEqual({ key: 'approvals.card.hl.permission_bare', params: { who: 'nova' } });
    expect(say(card.headline)).not.toMatch(/proceed/i);
    expect(card.facts.map((f) => f.id)).not.toContain('tool');
    const long = 'Do you want to allow claude to fetch this content from the web site?';
    const cut = cardContract({ ...bare, question: long, body: ` ${long}\n ❯ 1. Yes\n   2. No`, summary: 'Do you want to allow claude to fetch...' });
    expect(cut.headline).toEqual({ key: 'approvals.card.hl.permission_bare', params: { who: 'nova' } });
  });
});

describe('a codex approval', () => {
  test('the command, codex\'s own reason and the risk; beast mode would answer it', () => {
    const card = cardContract({
      id: 'dlg:ses_2:ef', source: 'dialog', host: 'local', session_id: 'ses_2', session_name: 'sage', family: 'codex',
      kind: 'codex_approval', question: 'Would you like to run the following command?', plain_yes: 'Yes, proceed',
      summary: 'command: pip install -r requirements.txt',
      body: 'Would you like to run the following command?\nEnvironment: local\nReason: needs network to download packages\n$ pip install -r requirements.txt\n1. Yes, proceed (y)\n2. No (esc)',
      rows: [{ label: 'Yes, proceed (y)', role: 'option' }, { label: 'No (esc)', role: 'option' }],
    });
    expect(card.kind).toBe('codex');
    expect(card.tone).toBe('codex');
    expect(say(card.headline)).toBe('sage (codex) wants your ok to run a command.');
    expect(facts(card).command).toBe('pip install -r requirements.txt');
    expect(facts(card).why).toBe('needs network to download packages');
    expect(card.chip).toBe('beast');
  });
});

describe('a question', () => {
  const ASK: ApprovalItem = {
    id: 'dlg:ses_2:aa', source: 'dialog', session_id: 'ses_2', session_name: 'nova', family: 'claude', kind: 'ask_user_question',
    question: 'Which screens first?', rows: [{ label: 'questions tab only', role: 'option' }, { label: 'both', role: 'option' }, { label: 'Type something', role: 'other' }],
  };

  test('one question: how to answer and how many options; it always waits', () => {
    const card = cardContract(ASK);
    expect(card.kind).toBe('question');
    expect(card.tone).toBe('ask');
    expect(say(card.headline)).toBe('nova has a question for you.');
    expect(facts(card)).toEqual({ answer: 'pick one', choices: '2 options' });
    expect(card.raw).toBeNull();
    expect(card.chip).toBe('waits');
  });

  test('several questions say how many answers it needs', () => {
    const card = cardContract({ ...ASK, multi_select: true, question_total: 2, question_index: 1, tabs: [{ title: 'scope', answered: false }, { title: 'tests', answered: false }] });
    expect(say(card.headline)).toBe('nova needs 2 answers from you before it continues.');
    expect(facts(card).answer).toBe('pick any number');
  });
});

describe('a plan, an unreadable prompt and any other dialog', () => {
  test('plan: what yes does and what happens otherwise; the plan text under details', () => {
    const card = cardContract({ id: 'p', source: 'dialog', session_name: 'vega', kind: 'plan_approval', question: 'Would you like to proceed?', body: 'Plan: split the store', rows: [{ label: 'Yes', role: 'option' }] });
    expect(card.kind).toBe('plan');
    expect(card.tone).toBe('plan');
    expect(say(card.headline)).toBe('vega has a plan ready and wants your go-ahead to start.');
    expect(card.facts.map((f) => f.id)).toEqual(['if_yes', 'otherwise']);
    expect(card.raw).toEqual({ kind: 'text', text: 'Plan: split the store' });
    expect(card.chip).toBe('waits');
  });

  test('unreadable: read only, open the session', () => {
    const card = cardContract({ id: 'u', source: 'dialog', session_name: 'orion', family: 'codex', kind: 'unreadable', question: '', body: '' });
    expect(card.kind).toBe('unreadable');
    expect(card.tone).toBe('raw');
    expect(card.chip).toBe('read_only');
    expect(facts(card)).toEqual({ looks_like: 'a codex prompt', next: 'open the session to answer it' });
    expect(card.raw).toBeNull();
  });

  test('another dialog: how many options', () => {
    const card = cardContract({ id: 'o', source: 'dialog', session_name: 'orion', kind: 'other', question: 'Pick a model', rows: [{ label: 'a', role: 'option' }, { label: 'b', role: 'option' }, { label: 'c', role: 'option' }] });
    expect(card.kind).toBe('dialog');
    expect(say(card.headline)).toBe('orion is waiting for you to pick an option.');
    expect(facts(card)).toEqual({ choices: '3 options' });
  });
});

describe('an agent action', () => {
  const ACTION: ApprovalItem = {
    id: 'act_1', source: 'agent_action', caller: 'carnivore_nova', session_id: 'ses_1', tmux_session: 'carnivore_omega',
    session_name: 'omega', action: 'project_move', summary: 'move ledgerbot',
    display: {
      verb: 'move', object: 'project', name: 'ledgerbot', tone: 'confirm',
      consequences: [{ key: 'summary', params: { text: 'moves to ~/Development/Org/Personal/ledgerbot' } }],
      detail: [{ key: 'new_folder', value: '/Users/x/Development/Org/Personal/ledgerbot' }],
    },
  };

  test('the caller asks to do the display\'s verb and object on its target; an mcp write', () => {
    const card = cardContract(ACTION, { rows: ROWS });
    expect(card.kind).toBe('agent');
    expect(card.tone).toBe('agent');
    expect(card.who).toBe('nova');
    expect(say(card.headline)).toBe('nova asks to move project ledgerbot.');
    expect(card.facts.map((f) => f.id)).toEqual(['effect', 'target', 'tool']);
    expect(facts(card).target).toBe('omega');
    expect(facts(card).tool).toBe('project_move');
    expect(card.raw).toEqual({ kind: 'agent', rows: ACTION.display!.detail, text: '' });
    expect(card.chip).toBe('mcp');
  });

  test('an older server with no display: the tool and the summary; an external client by its name', () => {
    const card = cardContract({ ...ACTION, display: null, external_client: 'phone' }, { rows: ROWS });
    expect(card.who).toBe('phone');
    expect(say(card.headline)).toBe('phone asks to run project_move.');
    expect(facts(card).effect).toBe('move ledgerbot');
  });
});

describe('the rules every card shares', () => {
  test('no card shows more than four facts', () => {
    const many = cardContract({
      id: 'act_2', source: 'agent_action', caller: 'carnivore_nova', action: 'session_purge', session_name: 'omega', tmux_session: 'carnivore_omega',
      display: { verb: 'purge', object: 'session', name: 'x', tone: 'danger', detail: [],
        consequences: [{ key: 'summary', params: { text: 'one' } }, { key: 'summary', params: { text: 'two' } }, { key: 'summary', params: { text: 'three' } }],
        in_use: { tone: 'alert', parts: [{ key: 'dialog' }] } },
    }, { rows: ROWS });
    expect(many.facts.length).toBe(MAX_FACTS);
    expect(many.facts.find((f) => f.id === 'in_use')?.tone).toBe('warn');
  });

  test('beast mode answers only a local plain yes that is no startup screen and no multi-question ask', () => {
    expect(beastWouldAnswer(BASH)).toBe(true);
    expect(beastWouldAnswer({ ...BASH, host: 'studio' })).toBe(false);
    expect(beastWouldAnswer({ ...BASH, startup_kind: 'trust' })).toBe(false);
    expect(beastWouldAnswer({ ...BASH, plain_yes: null })).toBe(false);
    expect(beastWouldAnswer({ ...BASH, tabs: [{ title: 'a', answered: false }] })).toBe(false);
    expect(cardContract({ ...BASH, host: 'studio' }).host).toBe('studio');
  });

  test('fixed labels read in plain words; any other label as written', () => {
    expect(say(optionWords('Yes, I trust this folder'))).toBe('yes, trust this folder');
    expect(say(optionWords('No, exit'))).toBe('no, exit');
    expect(say(optionWords('Yes, and always allow access to /tmp/Work'))).toBe('Yes, and always allow access to /tmp/Work');
  });

  test('option tones: a quit is danger, a startup yes confirms, everything else is quiet', () => {
    expect(cardOptionTone(TRUST, 'No, exit')).toBe('danger');
    expect(cardOptionTone(TRUST, 'Yes, I trust this folder')).toBe('confirm');
    expect(cardOptionTone(BASH, 'Yes')).toBe('secondary');
  });

  test('a multi-question ask is remembered per ask, its review screen per session, anything else per item', () => {
    expect(foldKey(BASH)).toBe('dlg:ses_2:cd');
    const tabs = [{ title: 'Scope', answered: true }, { title: 'Order', answered: false }];
    expect(foldKey({ ...BASH, tabs })).toBe('ses_2:ask:Scope|Order');
    expect(foldKey({ ...BASH, tabs: [{ title: 'Color', answered: false }, { title: 'Order', answered: false }] })).not.toBe(foldKey({ ...BASH, tabs }));
    const review: ApprovalItem = { ...BASH, kind: 'ask_user_question', question: ASK_REVIEW_QUESTION, tabs: [] };
    expect(foldKey(review)).toBe(askReviewKey('ses_2'));
    expect(foldKey({ ...review, question: 'Which?' })).toBe('dlg:ses_2:cd');
  });

  test('midCut keeps both ends', () => {
    expect(midCut('short')).toBe('short');
    expect(midCut('/a/very/long/path/to/project', 12)).toBe('/a/ve...ject');
  });
});
