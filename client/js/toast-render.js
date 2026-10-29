
console.log('[ToastRender Module] Loading...');

if (typeof ToastManager !== 'function') {
    throw new Error(
        'toast-render.js loaded before toast.js - class ToastManager is '
        + 'not defined. Fix the script order in client/index.html.'
    );
}

Object.assign(ToastManager.prototype, {
    /*  hidden  */
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
      const container = this._container();
      if (!container) return;

      const groups = this._groups();
      const cap = this._cap();
      const exemptCount = groups.filter((g) => g.severity >= CAP_EXEMPT_SEVERITY).length;
      const naturalCap = Math.max(cap, exemptCount);
      //  hidden 
      //  hidden 
      if (groups.length <= naturalCap) this._expanded = false;

      const effectiveCap = this._expanded ? groups.length : naturalCap;
      const visible = groups.slice(0, effectiveCap);
      const hidden = groups.slice(effectiveCap);

      const keep = new Set(visible.map((g) => g.key));
      for (const el of Array.from(container.querySelectorAll('.toast'))) {
        if (!keep.has(el.dataset.groupKey) && !el.classList.contains('toast--dismissing')) {
          el.remove();
        }
      }

      let prev = this._renderDismissAll(groups, container);
      const mode = globalThis.ToastMode;
      const waiting = mode && typeof mode.renderWaiting === 'function'
        ? mode.renderWaiting(groups, container, prev) : null;
      if (waiting) prev = waiting;
      for (const group of visible) {
        const el = this._renderCard(group, container);
        if (prev) {
          if (prev.nextSibling !== el) container.insertBefore(el, prev.nextSibling);
        } else if (container.firstChild !== el) {
          container.insertBefore(el, container.firstChild);
        }
        prev = el;
      }

      this._renderOverflow(hidden, container, prev);
    },

    /* would be pure chrome */
    _renderDismissAll(groups, container) {
      const total = groups.length;
      let row = container.querySelector('.toast-dismiss-all');
      if (total < 2) {
        if (row) row.remove();
        return null;
      }
      if (!row) {
        row = document.createElement('button');
        row.type = 'button';
        row.className = 'toast-dismiss-all';
        row.addEventListener('click', () => this.dismissAll());
      }
      const blocking = this._countBySeverity(groups, CAP_EXEMPT_SEVERITY);
      const label = blocking
        ? `Dismiss all ${total} notifications, including ${blocking} `
          + `waiting on your permission`
        : `Dismiss all ${total} notifications`;
      row.dataset.total = String(total);
      row.dataset.blocking = String(blocking);
      row.setAttribute('aria-label', label);
      row.textContent = `Dismiss all (${total})`;
      if (container.firstChild !== row) {
        container.insertBefore(row, container.firstChild);
      }
      return row;
    },

    _renderCard(group, container) {
      const { winner, count, badgeCount, severity, key } = group;
      let el = container.querySelector(
        `.toast[data-group-key="${CSS_ESC(key)}"]:not(.toast--dismissing)`);
      const isNew = !el;
      if (isNew) {
        el = document.createElement('div');
        el.className = 'toast toast--entering';
        el.dataset.groupKey = key;
      }
      el.dataset.toastId = winner.id;
      el.dataset.kind = winner.kind || '';
      el.dataset.severity = String(severity);
      if (winner.alert_severity) el.dataset.alertSeverity = String(winner.alert_severity);
      else delete el.dataset.alertSeverity;
      el.dataset.count = String(count);
      if (winner.color) {
        el.style.setProperty('--toast-accent', winner.color);
        el.dataset.themed = '1';
      }
      el.setAttribute('role', severity >= CAP_EXEMPT_SEVERITY ? 'alert' : 'status');

      el.textContent = '';

      const title = document.createElement('div');
      title.className = 'toast__title';
      if (winner.kind === AUTO_SLEEP_TOAST_KIND) {
        const icon = document.createElement('span');
        icon.className = 'toast__title-icon';
        const glyphs = window.SessionRowMenuIcons;
        icon.innerHTML = (glyphs && typeof glyphs.svg === 'function')
          ? glyphs.svg('sleep', 13) : '';
        title.appendChild(icon);
      }
      const titleText = document.createElement('span');
      titleText.className = 'toast__title-text';
      const mode = globalThis.ToastMode;
      const detailed = !!(mode && typeof mode.isDetailed === 'function' && mode.isDetailed());
      el.dataset.mode = detailed ? 'detailed' : 'compact';
      titleText.textContent = (detailed ? mode.headline(winner) : winner.title) || '(untitled)';
      title.appendChild(titleText);
      // permission prompt
      if (badgeCount > 1) {
        const badge = document.createElement('span');
        badge.className = 'toast__count';
        badge.textContent = `×${badgeCount}`;
        badge.setAttribute('aria-label', `${badgeCount} occurrences`);
        title.appendChild(badge);
      }
      if (window.ToastCollapse && typeof window.ToastCollapse.renderToggle === 'function') {
        window.ToastCollapse.renderToggle(
          title, el, !!winner.body || winner.kind === ATTACHMENT_KIND);
      }
      el.appendChild(title);

      // <button>
      const canNavigate = !!winner.session_name;
      const session = document.createElement(canNavigate ? 'button' : 'div');
      session.className = 'toast__session';
      if (canNavigate) session.type = 'button';
      const resolved = window.SessionLabel
        ? window.SessionLabel.resolveToast(winner)
        : (winner.session_label || winner.session_name || null);
      session.textContent = resolved
        || (window.SessionLabel ? window.SessionLabel.UNKNOWN : 'unknown session');
      if (!resolved) session.dataset.unknown = '1';
      if (canNavigate) {
        session.addEventListener('click', () => {
          this.dismissGroup(key);
        });
      }
      el.appendChild(session);

      const bodyText = detailed ? mode.snippet(winner) : winner.body;
      if (bodyText) {
        const body = document.createElement('div');
        body.className = 'toast__body';
        body.textContent = bodyText;
        el.appendChild(body);
      }

      if (winner.local && winner.action_label && typeof winner.on_action === 'function') {
        const action = document.createElement('button');
        action.type = 'button';
        action.className = 'modal-btn modal-btn-secondary toast__action';
        action.textContent = winner.action_label;
        action.addEventListener('click', (evt) => {
          if (evt && typeof evt.stopPropagation === 'function') evt.stopPropagation();
          winner.on_action();
          this.dismissGroup(key);
        });
        el.appendChild(action);
      }

      if (winner.kind === ATTACHMENT_KIND
          && window.AttachmentToast
          && typeof window.AttachmentToast.renderThumbs === 'function') {
        window.AttachmentToast.renderThumbs(el, group.toasts);
      }

      el.dataset.sessionId = winner.session_id || '';
      const openLocal = typeof winner.on_open === 'function' ? winner.on_open : null;
      if ((winner.session_id && window.ToastNavigate) || openLocal) {
        el.classList.add('toast--clickable');
        el.setAttribute('tabindex', '0');
        el._toastOpen = () => {
          if (openLocal) {
            openLocal();
            this.dismissGroup(key);
            return;
          }
          window.ToastNavigate.open(winner);
          if (detailed || window.ToastNavigate.isAskToast(winner)) this.dismissGroup(key);
        };
        if (!el._toastOpenBound) {
          el._toastOpenBound = true;
          el.addEventListener('click', () => el._toastOpen && el._toastOpen());
          el.addEventListener('keydown', (evt) => {
            if (evt.key === 'Enter' || evt.key === ' ') {
              evt.preventDefault();
              if (el._toastOpen) el._toastOpen();
            }
          });
        }
      }

      const dismissBtn = document.createElement('button');
      dismissBtn.type = 'button';
      dismissBtn.className = 'toast__dismiss';
      const label = count > 1
        ? `Dismiss ${count} notifications for this session`
        : 'Dismiss notification';
      dismissBtn.setAttribute('aria-label', label);
      dismissBtn.setAttribute('title', label);
      dismissBtn.textContent = '×';
      dismissBtn.addEventListener('click', (evt) => {
        // session it was about
        if (evt && typeof evt.stopPropagation === 'function') evt.stopPropagation();
        this.dismissGroup(key);
      });
      el.appendChild(dismissBtn);

      if (window.NotifyMute && typeof window.NotifyMute.attach === 'function') window.NotifyMute.attach(el, winner);

      if (isNew) {
        container.appendChild(el);
        void el.offsetWidth;
        requestAnimationFrame(() => el.classList.remove('toast--entering'));
      }
      return el;
    },

    /*  hidden  */
    _renderOverflow(hidden, container, prev) {
      let row = container.querySelector('.toast-overflow');
      if (hidden.length === 0 && !this._expanded) {
        if (row) row.remove();
        return;
      }
      if (!row) {
        row = document.createElement('button');
        row.type = 'button';
        row.className = 'toast-overflow';
        row.addEventListener('click', () => {
          this._expanded = !this._expanded;
          this._scheduleRender();
        });
      }

      if (this._expanded) {
        row.textContent = window.CloudeI18n.t('toast.show_fewer');
        row.dataset.hiddenCount = '0';
        row.dataset.worstSeverity = '0';
        row.setAttribute('aria-expanded', 'true');
      } else {
        const toastCount = hidden.reduce((n, g) => n + g.count, 0);
        const worst = hidden.reduce((m, g) => Math.max(m, g.severity), 0);
        row.dataset.hiddenCount = String(toastCount);
        row.dataset.worstSeverity = String(worst);
        row.setAttribute('aria-expanded', 'false');
        row.textContent = '';
        const n = document.createElement('span');
        n.className = 'toast-overflow__count';
        n.textContent = `+${toastCount} more`;
        row.appendChild(n);
        const worstLabel = OVERFLOW_SEVERITY_LABEL[worst];
        if (worstLabel) {
          const w = document.createElement('span');
          w.className = 'toast-overflow__worst';
          //  hidden 
          // waiting on the user
          w.textContent = '(' + worstLabel(
            this._countBySeverity(hidden, worst, true),
          ) + ')';
          row.appendChild(w);
        }
      }
      row.dataset.severity = row.dataset.worstSeverity;

      if (prev) {
        if (prev.nextSibling !== row) container.insertBefore(row, prev.nextSibling);
      } else if (container.firstChild !== row) {
        container.insertBefore(row, container.firstChild);
      }
    },
});

const AUTO_SLEEP_TOAST_KIND = 'AutoSlept';

const OVERFLOW_SEVERITY_LABEL = {
  2: (n) => (n === 1 ? '1 waiting on you' : `${n} waiting on you`),
};

function CSS_ESC(value) {
  return String(value).replace(/["\\]/g, '\\$&');
}
