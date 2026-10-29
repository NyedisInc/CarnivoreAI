
'use strict';

const fs = require('fs');
const { SESSION_ID_RE, customLaunch, runCustom } = require('./open-in-terminal');
const { canonicalFolder } = require('./finder-drop');
const { isRow, isLocal } = require('./tray-menu/session-rows');
const { senderAllowed } = require('./desktop-settings');
const confirm = require('./terminal-confirm');

const REVEAL_CHANNEL = 'carnivore:reveal-by-id';
const EDITOR_CHANNEL = 'carnivore:open-in-editor';
const PROJECT_ID_RE = /^project:[0-9]{1,15}$/;
const REASONS = Object.freeze({ ok: 'ok', remote: 'remote', missing: 'missing', noEditor: 'no_editor', cancelled: 'cancelled', failed: 'failed' });

function createFolderTargets(deps) {
  const io = deps.fs || fs;
  const answer = (ok, reason, error) => ({ ok, reason, error: error || null });

  async function notice(titleKey, messageKey, detail) {
    const t = await deps.loadTranslator();
    await deps.dialog.showMessageBox({ type: 'info', title: t(titleKey), message: t(messageKey), detail: detail || '', buttons: ['OK'], noLink: true });
  }

  async function resolveFolder(id) {
    const fail = (reason, error) => ({ ok: false, folder: null, reason, error: error || null });
    if (typeof id === 'string' && id.startsWith('remote:')) return fail(REASONS.remote);
    const isProject = typeof id === 'string' && PROJECT_ID_RE.test(id);
    if (typeof id !== 'string' || !(isProject || SESSION_ID_RE.test(id))) return fail(REASONS.failed, 'not a session or project id');
    const api = deps.api();
    if (!api) return fail(REASONS.failed, 'the server is not reachable');
    let raw = null;
    if (isProject) {
      const listed = await api.getAuthed('/api/v1/projects');
      if (!listed.reachable) return fail(REASONS.failed, listed.error || 'the server did not answer');
      const wanted = Number(id.slice('project:'.length));
      const row = (Array.isArray(listed.data) ? listed.data : []).find((p) => p && p.id === wanted);
      raw = row ? (row.root || row.path) : null;
    } else {
      const listed = await api.fetchSessions();
      if (!listed.reachable) return fail(REASONS.failed, listed.error || 'the server did not answer');
      const row = (listed.sessions || []).find((r) => isRow(r) && r.session.id === id);
      if (row && !isLocal(row)) return fail(REASONS.remote);
      raw = row ? row.session.working_dir : null;
    }
    const folder = canonicalFolder(raw, { fs: io });
    if (!folder.ok) {
      await notice('menubar.drop.add_title', 'menubar.reveal.missing', typeof raw === 'string' ? raw.slice(0, 300) : '');
      return fail(REASONS.missing);
    }
    return { ok: true, folder: folder.path, reason: REASONS.ok, error: null };
  }

  /* could not be read */
  async function readEditor() {
    const api = deps.api();
    const read = api ? await api.getAuthed('/api/v1/config/settings') : null;
    const workspace = read && read.reachable && read.data ? read.data.workspace : null;
    if (!workspace || typeof workspace !== 'object') return null;
    return typeof workspace.default_editor === 'string' ? workspace.default_editor.trim() : '';
  }

  return {
    resolveFolder,

    async reveal(id) {
      try {
        const found = await resolveFolder(id);
        if (!found.ok) return answer(false, found.reason, found.error);
        deps.shell.showItemInFolder(found.folder);
        return answer(true, REASONS.ok);
      } catch (error) {
        return answer(false, REASONS.failed, String((error && error.message) || error));
      }
    },

    async openInEditor(id) {
      try {
        const found = await resolveFolder(id);
        if (!found.ok) return answer(false, found.reason, found.error);
        const editor = await readEditor();
        if (editor === null) return answer(false, REASONS.failed, 'the editor setting could not be read');
        if (!editor) {
          await notice('menubar.editor.none_title', 'menubar.editor.none_message');
          return answer(false, REASONS.noEditor);
        }
        const launch = customLaunch(editor, [found.folder]);
        if (!launch.ok) return answer(false, REASONS.failed, launch.error);
        const t = await deps.loadTranslator();
        const approved = await confirm.confirmCustom({
          argv: [launch.file, ...launch.args], hashParts: [launch.file, ...launch.args.slice(0, -1)], dir: deps.dataDir(),
          dialog: deps.dialog, t, fs: io, file: confirm.EDITOR_CONFIRMED_FILE,
          titleKey: 'menubar.editor.confirm_title', bodyKey: 'menubar.editor.confirm_body',
        });
        if (!approved) return answer(false, REASONS.cancelled);
        const ran = await runCustom(launch.file, launch.args, { spawn: deps.spawn });
        if (!ran.opened) {
          await notice('menubar.drop.add_title', 'menubar.editor.failed', ran.error || '');
          return answer(false, REASONS.failed, ran.error);
        }
        return answer(true, REASONS.ok);
      } catch (error) {
        return answer(false, REASONS.failed, String((error && error.message) || error));
      }
    },
  };
}

function registerFolderTargets(deps) {
  const targets = createFolderTargets(deps);
  deps.ipcMain.handle(REVEAL_CHANNEL, async (event, id) => (senderAllowed(event, deps) ? targets.reveal(id) : null));
  deps.ipcMain.handle(EDITOR_CHANNEL, async (event, id) => (senderAllowed(event, deps) ? targets.openInEditor(id) : null));
  return targets;
}

module.exports = { REVEAL_CHANNEL, EDITOR_CHANNEL, PROJECT_ID_RE, REASONS, createFolderTargets, registerFolderTargets };
