/*  hidden  */

console.log('[Toast Module] Loading...');

const ATTACHMENT_KIND = 'Attachment';

const WRITE_FAILED_KIND = 'WriteFailed';

const SURVIVES_TYPING = new Set([ATTACHMENT_KIND]);

const TOAST_SEVERITY = {
  PermissionRequest: 3,
  Notification: 2,
  Stop: 1,
  // permission prompt
  [ATTACHMENT_KIND]: 1,
  [WRITE_FAILED_KIND]: 3,
};
const SEVERITY_DEFAULT = 2;

const CAP_EXEMPT_SEVERITY = 3;

const CAP_DESKTOP = 3;
const CAP_NARROW = 2;
const NARROW_QUERY = '(max-width: 640px)';

/*  hidden  */
const COALESCE_KEY = {
  [ATTACHMENT_KIND]: (t) => `${t.session_id}|${ATTACHMENT_KIND}`,
};

class ToastManager {
  constructor(containerId = 'toast-container') {
    this.containerId = containerId;
    this.ATTACHMENT_KIND = ATTACHMENT_KIND;
    this.WRITE_FAILED_KIND = WRITE_FAILED_KIND;
    this._byId = new Map();
    this._addedAt = new Map();
    this._now = () => Date.now();
    this._expanded = false;
    this._renderPending = false;
    this._containerPrepared = false;
    this._narrowQuery = null;
    this._bindViewportWatch();
  }

  _bindViewportWatch() {
    if (typeof window === 'undefined' || !window.matchMedia) return;
    try {
      this._narrowQuery = window.matchMedia(NARROW_QUERY);
      const onChange = () => this._scheduleRender();
      if (typeof this._narrowQuery.addEventListener === 'function') {
        this._narrowQuery.addEventListener('change', onChange);
      } else if (typeof this._narrowQuery.addListener === 'function') {
        this._narrowQuery.addListener(onChange);
      }
    } catch (err) {
      console.warn('[Toast] viewport watch unavailable:', err && err.message);
    }
  }

  _container() {
    const el = document.getElementById(this.containerId);
    if (el && !this._containerPrepared) {
      // permission prompt
      el.setAttribute('aria-live', 'polite');
      el.setAttribute('aria-relevant', 'additions text');
      this._containerPrepared = true;
    }
    return el;
  }
}

window.ToastManager = new ToastManager();
console.log('[Toast Module] Exported as window.ToastManager:', window.ToastManager);
