
console.log('[TextPromptModal Module] Loading...');

(function () {
    function defaultEscapeHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function open(options) {
        const opts = options || {};
        const esc = opts.escapeHtml || defaultEscapeHtml;
        const title = opts.title || '';
        const label = opts.label || '';
        const placeholder = opts.placeholder || '';
        const defaultValue = opts.defaultValue || '';
        const confirmLabel = opts.confirmLabel || 'ok';
        const cancelLabel = opts.cancelLabel || 'cancel';

        return new Promise((resolve) => {
            const overlay = document.createElement('div');
            overlay.className = 'modal-overlay text-prompt-modal';

            overlay.innerHTML = `
                <div class="modal-content">
                    <div class="text-prompt-modal__head">
                        <span class="text-prompt-modal__verb">&raquo; ${esc(title)}</span>
                    </div>
                    <div class="modal-body">
                        <div class="modal-input-group">
                            <label class="modal-label" for="text-prompt-modal-input">${esc(label)}</label>
                            <input type="text" class="modal-input" id="text-prompt-modal-input"
                                   autocomplete="off" spellcheck="false"
                                   placeholder="${esc(placeholder)}" value="${esc(defaultValue)}">
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button class="modal-btn modal-btn-secondary" id="text-prompt-modal-cancel">${esc(cancelLabel)}</button>
                        <button class="modal-btn modal-btn-confirm" id="text-prompt-modal-confirm">${esc(confirmLabel)}</button>
                    </div>
                </div>
            `;

            document.body.appendChild(overlay);

            const input = overlay.querySelector('#text-prompt-modal-input');
            const confirmBtn = overlay.querySelector('#text-prompt-modal-confirm');
            const cancelBtn = overlay.querySelector('#text-prompt-modal-cancel');

            let releaseTrap = () => {};
            let settled = false;

            const settle = (value) => {
                if (settled) return;
                settled = true;
                if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
                releaseTrap();
                resolve(value);
            };

            if (window.ModalStack && typeof window.ModalStack.trap === 'function') {
                releaseTrap = window.ModalStack.trap(overlay, {
                    onEscape: () => settle(null),
                });
            }

            confirmBtn.addEventListener('click', () => settle(input.value));
            cancelBtn.addEventListener('click', () => settle(null));

            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) settle(null);
            });

            input.addEventListener('keydown', (e) => {
                if (e.key !== 'Enter') return;
                e.preventDefault();
                settle(input.value);
            });

            setTimeout(() => {
                input.focus();
                if (defaultValue) input.select();
            }, 100);
        });
    }

    window.TextPromptModal = { open };
    console.log('[TextPromptModal Module] Exported as window.TextPromptModal');
})();
