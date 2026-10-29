
console.log('[ToastCollapse Module] Loading...');

(function () {
    'use strict';

    /* viewBox="0 0 12 12" */
    function buildChevron() {
        if (typeof document.createElementNS !== 'function') return null;
        var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('width', '10');
        svg.setAttribute('height', '10');
        svg.setAttribute('viewBox', '0 0 12 12');
        svg.setAttribute('fill', 'none');
        svg.setAttribute('stroke', 'currentColor');
        svg.setAttribute('stroke-width', '2');
        svg.setAttribute('stroke-linecap', 'round');
        svg.setAttribute('stroke-linejoin', 'round');
        svg.innerHTML = '<path d="M4 2l4 4-4 4"></path>';
        return svg;
    }

    function paintState(btn, expanded) {
        btn.setAttribute('aria-expanded', expanded ? 'true' : 'false');
        var label = expanded ? 'hide full notification' : 'show full notification';
        btn.setAttribute('aria-label', label);
        btn.setAttribute('title', label);
    }

    /* there is nothing */
    function renderToggle(titleEl, cardEl, canExpand) {
        if (!titleEl || !cardEl || !canExpand) return;

        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'toast__toggle';
        paintState(btn, cardEl.dataset.expanded === '1');

        var chevron = buildChevron();
        if (chevron) {
            var wrap = document.createElement('span');
            wrap.className = 'toast__toggle-chevron';
            wrap.setAttribute('aria-hidden', 'true');
            wrap.appendChild(chevron);
            btn.appendChild(wrap);
        }

        btn.addEventListener('click', function toggleClick(evt) {
            if (evt && typeof evt.stopPropagation === 'function') evt.stopPropagation();
            var next = cardEl.dataset.expanded === '1' ? '0' : '1';
            cardEl.dataset.expanded = next;
            paintState(btn, next === '1');
        });

        titleEl.appendChild(btn);
    }

    window.ToastCollapse = {
        renderToggle: renderToggle,
    };
})();
