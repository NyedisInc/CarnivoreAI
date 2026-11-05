import test from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const mac = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'macOS');
const { createBanners } = require(path.join(mac, 'banners', 'index.js'));

const dialog = (sessionId, fp) => ({
  id: `dlg:${sessionId}:aaaa`, source: 'dialog', host: 'local', session_id: sessionId, session_name: sessionId, kind: 'permission',
  question: 'Do you want to proceed?', options: ['Yes', 'No'], multi_select: false, has_other: false, fingerprint: fp.repeat(64),
  startup_kind: null, summary: 'Bash: ls', questions: [], questions_fingerprint: null, questions_state: null,
});

async function posted(values, watched = 'ses_a') {
  const shown = [];
  class N {
    constructor(opts) { this.opts = opts; }
    static isSupported() { return true; }
    on() {} show() { shown.push(this.opts); } close() {}
  }
  const items = [dialog('ses_a', 'a'), dialog('ses_b', 'b')];
  const api = { getAuthed: async (route) => (route.includes('approvals')
    ? { reachable: true, data: { items } } : { reachable: true, data: { values } }) };
  const banners = createBanners({ platform: 'darwin', getApi: () => api, Notification: N, readPermission: () => 'allowed', t: (k) => k,
    isWindowFocused: () => true, watchedSession: () => watched, openApproval: () => {} });
  await banners.onApprovals();
  return shown.map((o) => JSON.stringify(o).includes('ses_b') ? 'ses_b' : 'ses_a');
}

test('window in front: only the watched session is skipped; quiet off skips every banner as before', async () => {
  assert.deepEqual(await posted({}), ['ses_b'], 'quiet is on while absent: the other session still gets its banner');
  assert.deepEqual(await posted({ notify_quiet_watched: false }), [], 'quiet off: the window in front posts nothing');
  assert.deepEqual(await posted({}, ''), ['ses_a', 'ses_b'], 'nothing watched (Home, a menu page): every session posts');
});
