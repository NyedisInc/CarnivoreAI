// nothing at all

'use strict';

const { parseDeepLink, createFocusGate } = require('./deep-link');

const HOLD_MS = 60000;

/* could not */
function createLinkRouter({ appWindow, now = Date.now, warn = console.warn }) {
  const gate = createFocusGate({ now });
  let held = null;

  /* could not */
  function act(link) {
    return link.kind === 'approvals' ? appWindow.openApproval(link.approvalId) : appWindow.open(link.hash);
  }

  return {
    handle(text) {
      const link = parseDeepLink(text);
      if (!link.ok) {
        warn('[deep-link] refused:', link.reason);
        return link;
      }
      if (!gate.allow()) return { ok: false, reason: 'dropped: another link raised the window under 500 ms ago' };
      if (!act(link)) held = { link, at: now() };
      return { ok: true };
    },
    replay() {
      const pending = held;
      held = null;
      if (!pending || now() - pending.at > HOLD_MS) return;
      if (!act(pending.link)) held = pending;
    },
  };
}

module.exports = { createLinkRouter };
