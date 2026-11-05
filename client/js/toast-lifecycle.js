
console.log('[ToastLifecycle Module] Loading...');

if (typeof ToastManager !== 'function') {
    throw new Error(
        'toast-lifecycle.js loaded before toast.js - class ToastManager is '
        + 'not defined. Fix the script order in client/index.html.'
    );
}

Object.assign(ToastManager.prototype, {
    _isTerminalVisible() {
      if (document.hidden || document.visibilityState === 'hidden') return false;
      if (typeof document.hasFocus !== 'function' || !document.hasFocus()) return false;
      const screen = document.getElementById('terminal-screen');
      const home = document.getElementById('launchpad-screen');
      return !!screen && screen.classList.contains('active') && !(home && home.classList.contains('active'));
    },

    _isActiveSession(toast) {
      if (!this._isTerminalVisible()) return false;
      const sidebar = window.SessionSidebar;
      if (!sidebar || !toast) return false;
      const sid = toast.session_id;
      const name = toast.session_name;
      if (sid && sidebar._activeSessionId && sid === sidebar._activeSessionId) return true;
      if (name && sidebar._activeTmuxName && name === sidebar._activeTmuxName) return true;
      return false;
    },

    add(toast) {
      if (!toast || !toast.id) return;
      if (toast.acknowledged) return;
      if (!this._container()) return;
      if (window.NotifyScreen && window.NotifyScreen.shows(toast) === false) return;
      if (!toast.local && this._isActiveSession(toast)) return;
      if (this._byId.has(toast.id)) {
        const held = this._byId.get(toast.id);
        if (window.ToastVersionArbitration
            && !window.ToastVersionArbitration.shouldReplace(held, toast)) {
          return;
        }
        this._byId.set(toast.id, toast);
        this._scheduleRender();
        return;
      }
      this._byId.set(toast.id, toast);
      this._addedAt.set(toast.id, this._now());
      this._scheduleRender();
      this._desktopNotify(toast);
    },

    _desktopNotify(toast) {
      const bridge = window.carnivoreDesktop;
      if (!bridge || typeof bridge.notify !== 'function') return;
      const screen = window.NotifyScreen;
      const group = screen && typeof screen.groupOf === 'function' ? (screen.groupOf(toast.notify_type) || '') : '';
      if (document.hasFocus()) {
        const quiet = window.NotifyQuietWatched;
        if (!(quiet && typeof quiet.on === 'function' && quiet.on() === true && group === 'needs_you')) return;
      }
      const nav = window.ToastNavigate;
      const ask = nav && typeof nav.isAskToast === 'function' && nav.isAskToast(toast) ? toast.session_id : '';
      if (ask && this._bannersPosting === true) return;
      if (toast.notify_type === 'app.update_available') return;
      const label = window.SessionLabel && typeof window.SessionLabel.resolveToast === 'function' ? window.SessionLabel.resolveToast(toast) : null;
      bridge.notify(toast.title || '', toast.body || '', ask, {
        id: toast.local ? '' : String(toast.id || ''),
        group,
        subtitle: label || '',
        session_id: typeof toast.session_id === 'string' ? toast.session_id : '',
        tmux_name: typeof toast.session_name === 'string' ? toast.session_name : '',
      });
    },

    /* the card is gone */
    _desktopUnnotify(toast) {
      const bridge = window.carnivoreDesktop;
      if (!bridge || typeof bridge.unnotify !== 'function' || !toast || toast.local || !toast.id) return;
      bridge.unnotify(String(toast.id));
    },

    async _readBannersPosting() {
      const bridge = window.carnivoreDesktop;
      let posting = false;
      try {
        if (bridge && Array.isArray(bridge.capabilities) && bridge.capabilities.includes('desktopState')
            && typeof bridge.desktopState === 'function') {
          const state = await bridge.desktopState();
          posting = !!(state && state.notifications && state.notifications.banners
            && state.notifications.banners.posting === true);
        }
      } catch (error) {
        posting = false;
      }
      this._bannersPosting = posting;
    },

    reconcileOpen(openToasts, { since } = {}) {
      if (!Array.isArray(openToasts)) return 0;
      const open = new Set();
      for (const entry of openToasts) {
        if (!entry) continue;
        const id = (typeof entry === 'string') ? entry : entry.id;
        if (id) open.add(id);
      }
      const stale = [];
      for (const id of this._byId.keys()) {
        if (open.has(id)) continue;
        const toast = this._byId.get(id);
        if (toast && toast.local) continue;
        if (since !== undefined && since !== null) {
          const addedAt = this._addedAt.get(id);
          if (addedAt !== undefined && addedAt >= since) continue;
        }
        stale.push(id);
      }
      for (const id of stale) this.dismiss(id, { syncToServer: false });
      return stale.length;
    },

    pruneHidden(shows) {
      if (typeof shows !== 'function') return;
      const hidden = [];
      for (const [id, toast] of this._byId) {
        if (toast && !toast.local && shows(toast) === false) hidden.push(id);
      }
      for (const id of hidden) this.dismiss(id, { syncToServer: false });
    },

    dismiss(toastId, { syncToServer = true } = {}) {
      const toast = this._byId.get(toastId);
      if (!toast) return;
      this._byId.delete(toastId);
      this._desktopUnnotify(toast);
      this._addedAt.delete(toastId);

      if (!this._startFade(toastId)) this._scheduleRender();

      // no such record
      if (syncToServer && toast && toast.session_id && !toast.local) {
        this._ack(toastId, toast.session_id);
      }

      try {
        document.dispatchEvent(new CustomEvent('cloude:toast-dismissed', {
          detail: { id: toastId, sessionId: toast ? toast.session_id : null },
        }));
      } catch (err) {
      }
    },

    updateLocal(toastId, patch) {
      const toast = this._byId.get(toastId);
      if (!toast || !toast.local || !patch) return false;
      this._byId.set(toastId, Object.assign({}, toast, patch));
      this._scheduleRender();
      return true;
    },

    dismissKindForSession(kind, sessionId) {
      if (!kind || !sessionId) return 0;
      const ids = [];
      for (const [id, toast] of this._byId.entries()) {
        if (toast && toast.kind === kind && toast.session_id === sessionId) {
          ids.push(id);
        }
      }
      for (const id of ids) this.dismiss(id, { syncToServer: true });
      return ids.length;
    },

    dismissGroup(key) {
      const group = this._groups().find((g) => g.key === key);
      if (!group) return;
      for (const toast of group.toasts) {
        this.dismiss(toast.id, { syncToServer: true });
      }
    },

    _ack(toastId, sessionId) {
      if (window.API && typeof window.API.ackToast === 'function') {
        window.API.ackToast(toastId, sessionId).catch((err) => {
          console.warn('[Toast] ack failed', err && err.message);
        });
      }
    },

    dismissBySession(sessionId) {
      if (!sessionId) return;
      for (const [id, toast] of Array.from(this._byId.entries())) {
        if (toast && toast.session_id === sessionId) {
          this.dismiss(id, { syncToServer: false });
        }
      }
    },

    dismissForSessionEntry(sessionId, tmuxName) {
      if (!sessionId && !tmuxName) return 0;
      if (!this._isTerminalVisible()) return 0;
      const ids = [];
      for (const [id, toast] of this._byId.entries()) {
        if (!toast || toast.local) continue;
        if ((sessionId && toast.session_id === sessionId)
            || (tmuxName && toast.session_name === tmuxName)) {
          ids.push(id);
        }
      }
      for (const id of ids) this.dismiss(id, { syncToServer: true });
      return ids.length;
    },

    /* Claude is waiting no evidence at all */
    dismissForSessionActivity(sessionId, data) {
      if (!sessionId) return 0;
      if (data !== undefined && window.AttachmentToast
          && typeof window.AttachmentToast.noteUserInput === 'function') {
        window.AttachmentToast.noteUserInput(sessionId, data);
      }
      const ids = [];
      for (const [id, toast] of this._byId.entries()) {
        if (!toast || toast.session_id !== sessionId) continue;
        if (SURVIVES_TYPING.has(toast.kind)) continue;
        ids.push(id);
      }
      for (const id of ids) this.dismiss(id, { syncToServer: true });
      return ids.length;
    },

    dismissAll() {
      const ids = Array.from(this._byId.keys());
      for (const id of ids) this.dismiss(id, { syncToServer: true });
      this._expanded = false;
      return ids.length;
    },

    clearAll() {
      for (const id of Array.from(this._byId.keys())) {
        this.dismiss(id, { syncToServer: false });
      }
    },

    backfill(toasts) {
      if (!Array.isArray(toasts)) return;
      for (let i = toasts.length - 1; i >= 0; i--) {
        this.add(toasts[i]);
      }
    },
});

if (window.carnivoreDesktop && window.ToastManager && typeof window.ToastManager._readBannersPosting === 'function') {
    window.ToastManager._readBannersPosting();
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') window.ToastManager._readBannersPosting();
    });
}
