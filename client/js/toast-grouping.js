
console.log('[ToastGrouping Module] Loading...');

if (typeof ToastManager !== 'function') {
    throw new Error(
        'toast-grouping.js loaded before toast.js - class ToastManager is '
        + 'not defined. Fix the script order in client/index.html.'
    );
}

Object.assign(ToastManager.prototype, {
    _severity(kind) {
      const s = TOAST_SEVERITY[kind];
      return typeof s === 'number' ? s : SEVERITY_DEFAULT;
    },

    _cap() {
      const narrow = !!(this._narrowQuery && this._narrowQuery.matches);
      return narrow ? CAP_NARROW : CAP_DESKTOP;
    },

    _groupKeyFor(toast) {
      const keyFn = COALESCE_KEY[toast.kind];
      if (typeof keyFn === 'function') return keyFn(toast);
      const grouper = globalThis.ToastSessionGroup;
      if (grouper && typeof grouper.groupKey === 'function') {
        return grouper.groupKey(toast);
      }
      return null;
    },

    _pick(toasts) {
      const mode = globalThis.ToastMode;
      if (mode && typeof mode.isDetailed === 'function' && mode.isDetailed()) {
        const latest = mode.pickLatest(toasts);
        if (latest && latest.winner) return latest;
      }
      const grouper = globalThis.ToastSessionGroup;
      if (grouper && typeof grouper.pick === 'function') {
        const picked = grouper.pick(toasts, (kind) => this._severity(kind));
        if (picked && picked.winner) return picked;
      }
      return { winner: toasts[toasts.length - 1], count: toasts.length };
    },

    _groups() {
      const order = new Map();
      let idx = 0;
      for (const id of this._byId.keys()) order.set(id, idx++);
      const byKey = new Map();
      const singles = [];
      for (const toast of this._byId.values()) {
        const key = this._groupKeyFor(toast);
        if (!key) {
          singles.push({ key: `id:${toast.id}`, toasts: [toast] });
          continue;
        }
        const existing = byKey.get(key);
        if (existing) existing.toasts.push(toast);
        else byKey.set(key, { key, toasts: [toast] });
      }
      const groups = [...byKey.values()].concat(singles).map((g) => {
        const picked = this._pick(g.toasts);
        return {
          key: g.key,
          toasts: g.toasts,
          winner: picked.winner,
          count: g.toasts.length,
          badgeCount: picked.count,
          severity: g.toasts.reduce((m, t) => Math.max(m, this._severity(t.kind)), 0),
        };
      });
      groups.sort((a, b) => {
        if (b.severity !== a.severity) return b.severity - a.severity;
        return order.get(b.winner.id) - order.get(a.winner.id);
      });
      return groups;
    },

    _countBySeverity(groups, min, exact = false) {
      let n = 0;
      for (const group of groups) {
        for (const toast of group.toasts) {
          const sev = this._severity(toast.kind);
          if (exact ? sev === min : sev >= min) n += 1;
        }
      }
      return n;
    },
});
