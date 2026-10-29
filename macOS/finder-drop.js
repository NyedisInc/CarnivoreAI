
'use strict';

const fs = require('fs');
const os = require('os');
const path = require('path');

const MAX_FOLDERS = 5;
const BATCH_MS = 150;
const HOLD_MS = 60000;
const PROJECTS_ROUTE = '/api/v1/projects';
const NAME_ATTEMPTS = 20;

function canonicalFolder(input, deps) {
  const io = (deps && deps.fs) || fs;
  const home = ((deps && deps.os) || os).homedir();
  // eslint-disable-next-line no-control-regex
  if (typeof input !== 'string' || !input || /[\u0000-\u001f\u007f]/.test(input)) return { ok: false, path: null, reason: 'invalid' };
  let expanded = input;
  if (input === '~') expanded = home;
  else if (input.startsWith('~/')) expanded = path.join(home, input.slice(2));
  if (!path.isAbsolute(expanded)) return { ok: false, path: null, reason: 'invalid' };
  try {
    const real = io.realpathSync(path.resolve(expanded));
    return io.statSync(real).isDirectory() ? { ok: true, path: real, reason: null } : { ok: false, path: null, reason: 'not_folder' };
  } catch (error) {
    return { ok: false, path: null, reason: 'not_folder' };
  }
}

function findProject(projects, folder, deps) {
  for (const row of Array.isArray(projects) ? projects : []) {
    const root = row && typeof row.root === 'string' && row.root ? row.root : (row && row.path);
    const real = canonicalFolder(root, deps);
    if (real.ok && real.path === folder && typeof row.name === 'string' && row.name) return row;
  }
  return null;
}

function createFinderDrop(deps) {
  const io = { fs: deps.fs, os: deps.os };

  async function say(key, detail, buttons) {
    const t = await deps.loadTranslator();
    const result = await deps.dialog.showMessageBox({
      type: 'info', title: t('menubar.drop.add_title'), message: t(key), detail: detail || '',
      buttons: buttons ? buttons.map((b) => t(b)) : [t('menubar.drop.cancel')],
      defaultId: buttons ? 1 : 0, cancelId: buttons ? 1 : 0, noLink: true,
    });
    return result.response;
  }

  async function create(api, folder) {
    const base = path.basename(folder) || folder;
    for (let i = 0; i < NAME_ATTEMPTS; i += 1) {
      const name = i === 0 ? base : `${base} (${i + 1})`;
      const answer = await api.sendAuthed(PROJECTS_ROUTE, { name, path: folder }, 'POST');
      if (answer.reachable) return { name, refused: false };
      const body = answer.body || {};
      if (answer.status === 409 && body.existing_project && body.existing_project.name) return { name: String(body.existing_project.name), refused: false };
      if (answer.status === 409) return { name: null, refused: true };
      const taken = answer.status === 400 && /already exists/.test(String(body.detail || answer.error || ''));
      if (!taken) return { name: null, refused: false };
    }
    return { name: null, refused: false };
  }

  async function handleOne(api, projects, input) {
    const folder = canonicalFolder(input, io);
    if (!folder.ok) {
      await say('menubar.drop.not_folder', typeof input === 'string' ? input.slice(0, 300) : '');
      return { name: null };
    }
    const known = findProject(projects, folder.path, io);
    if (known) return { name: known.name };
    if ((await say('menubar.drop.add_message', folder.path, ['menubar.drop.add', 'menubar.drop.cancel'])) !== 0) return { name: null };
    const created = await create(api, folder.path);
    if (!created.name) await say(created.refused ? 'menubar.drop.refused' : 'menubar.drop.failed', folder.path);
    return { name: created.name };
  }

  return {
    async open(paths) {
      const api = deps.api();
      if (!api) return { done: false };
      const listed = await api.getAuthed(PROJECTS_ROUTE);
      if (!listed.reachable) return { done: false };
      const projects = listed.data;
      let first = null;
      for (const input of (Array.isArray(paths) ? paths : []).slice(0, MAX_FOLDERS)) {
        const { name } = await handleOne(api, projects, input);
        if (name && first === null) first = name;
      }
      if (first !== null && !deps.appWindow.open(`session/${encodeURIComponent(first)}`)) return { done: false };
      return { done: true };
    },
  };
}

function wireFinderDrop({ app, opener, now = Date.now }) {
  let held = null;
  let batch = [];
  let timer = null;
  let busy = Promise.resolve();

  function run(paths, at) {
    busy = busy.then(async () => {
      try {
        const result = await opener().open(paths);
        if (!result.done && now() - at <= HOLD_MS) held = { paths, at };
      } catch (error) {
        console.warn('[finder-drop] failed:', error && error.message);
      }
    });
    return busy;
  }

  app.on('open-file', (event, filePath) => {
    event.preventDefault();
    batch.push(filePath);
    if (!timer) {
      timer = setTimeout(() => {
        timer = null;
        const paths = batch.slice(0, MAX_FOLDERS);
        batch = [];
        void run(paths, now());
      }, BATCH_MS);
    }
  });

  return {
    handle: (paths) => run(paths, now()),
    async onServerUp() {
      const pending = held;
      held = null;
      if (pending && now() - pending.at <= HOLD_MS) await run(pending.paths, pending.at);
    },
  };
}

module.exports = { MAX_FOLDERS, BATCH_MS, HOLD_MS, canonicalFolder, findProject, createFinderDrop, wireFinderDrop };
