
console.log('[ToastView Module] Loading...');

if (typeof ToastManager !== 'function') {
    throw new ReferenceError('ToastManager');
}

const AUTO_SLEEP_TOAST_KIND = 'AutoSlept';

const FADE_MS = 220;

Object.assign(ToastManager.prototype, {
    subscribe(listener) {
      this._viewListeners.add(listener);
      listener(this._view);
      return () => { this._viewListeners.delete(listener); };
    },

    _publish(view) {
      this._view = view;
      for (const listener of Array.from(this._viewListeners)) {
        try {
          listener(view);
        } catch (err) {
          console.error('[Toast] view subscriber failed:', err && err.message);
        }
      }
    },

    _scheduleRender() {
      if (this._renderPending) return;
      this._renderPending = true;
      const flush = () => {
        this._renderPending = false;
        this._render();
      };
      if (window.ToastRenderBatch && typeof window.ToastRenderBatch.schedule === 'function') {
        window.ToastRenderBatch.schedule(flush);
      } else {
        flush();
      }
    },

    _render() {
      if (!this._container()) return;

      const groups = this._groups();
      const exemptCount = groups.filter((g) => g.severity >= CAP_EXEMPT_SEVERITY).length;
      const naturalCap = Math.max(this._cap(), exemptCount);
      if (groups.length <= naturalCap) this._expanded = false;

      const effectiveCap = this._expanded ? groups.length : naturalCap;
      const visible = groups.slice(0, effectiveCap);
      const hidden = groups.slice(effectiveCap);

      const mode = globalThis.ToastMode;
      const detailed = !!(mode && typeof mode.isDetailed === 'function' && mode.isDetailed());
      const cards = this._withFading(visible.map((group) => this._cardView(group, detailed)));
      this._publish({
        cards,
        dismissAll: this._dismissAllView(groups),
        waiting: mode && typeof mode.waitingRowCount === 'function' ? mode.waitingRowCount(groups) : null,
        overflow: this._overflowView(hidden),
      });
    },

    _dismissAllView(groups) {
      if (groups.length < 2) return null;
      return { total: groups.length, blocking: this._countBySeverity(groups, CAP_EXEMPT_SEVERITY) };
    },

    /* waiting on the user */
    _overflowView(hidden) {
      if (hidden.length === 0 && !this._expanded) return null;
      if (this._expanded) return { expanded: true, count: 0, worst: 0, worstCount: null };
      const count = hidden.reduce((n, g) => n + g.count, 0);
      const worst = hidden.reduce((m, g) => Math.max(m, g.severity), 0);
      const worstCount = worst === OVERFLOW_WORDED_SEVERITY ? this._countBySeverity(hidden, worst, true) : null;
      return { expanded: false, count, worst, worstCount };
    },

    _cardView(group, detailed) {
      const { winner, count, badgeCount, severity, key } = group;
      const mode = globalThis.ToastMode;
      const openLocal = typeof winner.on_open === 'function';
      const action = winner.local && winner.action_label && typeof winner.on_action === 'function';
      return {
        uid: this._uidGen.has(key) ? `${key}#${this._uidGen.get(key)}` : key,
        key,
        id: winner.id,
        kind: winner.kind || '',
        severity,
        alertSeverity: winner.alert_severity ? String(winner.alert_severity) : null,
        count,
        badgeCount,
        color: winner.color || null,
        role: severity >= CAP_EXEMPT_SEVERITY ? 'alert' : 'status',
        mode: detailed ? 'detailed' : 'compact',
        title: (detailed ? mode.headline(winner) : winner.title) || '',
        sleepIcon: winner.kind === AUTO_SLEEP_TOAST_KIND ? this._sleepGlyph() : null,
        session: this._sessionView(winner),
        sessionId: winner.session_id || '',
        body: (detailed ? mode.snippet(winner) : winner.body) || null,
        actionLabel: action ? winner.action_label : null,
        thumbs: winner.kind === ATTACHMENT_KIND ? group.toasts : null,
        canExpand: !!winner.body || winner.kind === ATTACHMENT_KIND,
        clickable: !!((winner.session_id && window.ToastNavigate) || openLocal),
        winner,
        dismissing: false,
      };
    },

    _sleepGlyph() {
      const glyphs = window.SessionRowMenuIcons;
      return (glyphs && typeof glyphs.svg === 'function') ? glyphs.svg('sleep', 13) : '';
    },

    _sessionView(winner) {
      const resolved = window.SessionLabel
        ? window.SessionLabel.resolveToast(winner)
        : (winner.session_label || winner.session_name || null);
      return {
        text: resolved || (window.SessionLabel ? window.SessionLabel.UNKNOWN : globalThis.CloudeTr('toast.session.unknown')),
        unknown: !resolved,
        canNavigate: !!winner.session_name,
      };
    },

    _withFading(cards) {
      if (this._fading.size === 0) return cards;
      const merged = cards.slice();
      for (const snapshot of this._fading.values()) {
        merged.splice(Math.min(snapshot.index, merged.length), 0, snapshot.card);
      }
      return merged;
    },

    _startFade(toastId) {
      const index = this._view.cards.findIndex((c) => c.id === toastId && !c.dismissing);
      if (index === -1) return false;
      const shown = this._view.cards[index];
      const card = Object.assign({}, shown, { dismissing: true });
      this._uidGen.set(shown.key, (this._uidGen.get(shown.key) || 0) + 1);
      this._fading.set(toastId, { card, index });
      this._publish(Object.assign({}, this._view, {
        cards: this._view.cards.map((c, i) => (i === index ? card : c)),
      }));
      setTimeout(() => {
        this._fading.delete(toastId);
        this._scheduleRender();
      }, FADE_MS);
      return true;
    },

    _groupFor(key) {
      return this._groups().find((g) => g.key === key);
    },

    _winnerFor(key) {
      const group = this._groupFor(key);
      if (group) return group.winner;
      const card = this._view.cards.find((c) => c.key === key);
      return card ? card.winner : undefined;
    },

    openGroup(key) {
      const winner = this._winnerFor(key);
      if (!winner) return;
      if (typeof winner.on_open === 'function') {
        winner.on_open();
        this.dismissGroup(key);
        return;
      }
      if (!window.ToastNavigate) return;
      window.ToastNavigate.open(winner);
      const mode = globalThis.ToastMode;
      const detailed = !!(mode && typeof mode.isDetailed === 'function' && mode.isDetailed());
      if (detailed || window.ToastNavigate.isAskToast(winner)) this.dismissGroup(key);
    },

    clickSession(key) {
      this.dismissGroup(key);
    },

    runCardAction(key) {
      const group = this._groupFor(key);
      if (!group || typeof group.winner.on_action !== 'function') return;
      group.winner.on_action();
      this.dismissGroup(key);
    },

    toggleOverflow() {
      this._expanded = !this._expanded;
      this._scheduleRender();
    },
});

const OVERFLOW_WORDED_SEVERITY = 2;
