(function () {
    'use strict';

    function tr(key, params) {
        var i18n = globalThis.CloudeI18n;
        return i18n && typeof i18n.t === 'function' ? i18n.t(key, params) : key;
    }

    var LINE_COUNT = 400;

    var sheetEl = null;

    var onDocKey = null;

    var CHIP_LABEL_MAX = 44;

    function readRecentOutput(term, lines) {
        var want = typeof lines === 'number' ? lines : LINE_COUNT;
        if (!term) return '';
        try {
            var buf = term.buffer.active;
            var end = buf.length;
            var start = Math.max(0, end - want);
            var cols = typeof term.cols === 'number' ? term.cols : 0;
            var rows = [];
            var current = null;
            var prevFilled = false;
            for (var i = start; i < end; i++) {
                var line = buf.getLine(i);
                var raw = line ? line.translateToString(false) : '';
                var continues = (line && line.isWrapped) || prevFilled;
                prevFilled = cols > 0 && raw.length >= cols &&
                    raw.charAt(cols - 1) !== ' ';
                if (continues && current !== null) {
                    current += raw;
                    continue;
                }
                if (current !== null) rows.push(current.replace(/\s+$/, ''));
                current = raw;
            }
            if (current !== null) rows.push(current.replace(/\s+$/, ''));
            while (rows.length && rows[0].trim() === '') rows.shift();
            while (rows.length && rows[rows.length - 1].trim() === '') rows.pop();
            return rows.join('\n');
        } catch (err) {
            console.warn('CopyOutput: buffer read failed', err);
            return '';
        }
    }

    function shortenForChip(value, max) {
        var limit = typeof max === 'number' ? max : CHIP_LABEL_MAX;
        var text = value || '';
        if (limit < 8 || text.length <= limit) return text;
        var keep = limit - 3;
        var head = Math.ceil(keep / 2);
        var tail = keep - head;
        return text.slice(0, head) + '...' + text.slice(text.length - tail);
    }

    var statusEl = null;

    var textEl = null;

    /* nothing at all */
    function setStatus(message, kind) {
        if (!statusEl) return;
        statusEl.textContent = message;
        statusEl.dataset.kind = kind || 'info';
    }

    function selectInRawText(value) {
        if (!textEl || !value) return false;
        var at = textEl.value.indexOf(value);
        if (at < 0) return false;
        try {
            textEl.focus({ preventScroll: true });
            textEl.setSelectionRange(at, at + value.length);
            return true;
        } catch (err) {
            console.warn('CopyOutput: could not preselect raw text', err);
            return false;
        }
    }

    function copyAndReport(termWrapper, text, label, source) {
        return window.CopyCompat.copyText(text).then(function (result) {
            if (result.ok) {
                setStatus(tr('copy_output.copied.status', { label: label }), 'success');
                if (source) {
                    source.classList.add('is-copied');
                    source.setAttribute('data-copied', 'copied');
                }
                if (termWrapper && termWrapper._showStatusPill) {
                    termWrapper._showStatusPill(tr('copy_output.copied.pill', { label: label }), 'success');
                }
            } else {
                var picked = selectInRawText(text);
                setStatus(
                    picked
                        ? tr('copy_output.blocked.selected', { label: label })
                        : tr('copy_output.blocked.plain'),
                    'error'
                );
            }
            return result;
        });
    }

    function buildChip(termWrapper, item) {
        var chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'cloude-copy-chip cloude-copy-chip--' + item.kind;
        chip.setAttribute('aria-label', tr('copy_output.chip.aria', { kind: item.kind, value: item.value }));
        chip.dataset.value = item.value;

        var kind = document.createElement('span');
        kind.className = 'cloude-copy-chip__kind';
        kind.textContent = item.kind;

        var value = document.createElement('span');
        value.className = 'cloude-copy-chip__value';
        value.textContent = shortenForChip(item.value);

        chip.appendChild(kind);
        chip.appendChild(value);

        if (item.value.length > CHIP_LABEL_MAX) {
            var size = document.createElement('span');
            size.className = 'cloude-copy-chip__size';
            size.textContent = item.value.length + ' chars';
            chip.appendChild(size);
        }

        chip.addEventListener('click', function () {
            copyAndReport(termWrapper, item.value, item.kind, chip);
        });
        return chip;
    }

    function isHttpUrl(value) {
        var stripped = String(value == null ? '' : value)
            .replace(/[\s -]+/g, '')
            .toLowerCase();
        return /^https?:\/\/[^/]/.test(stripped);
    }

    function buildRow(termWrapper, item) {
        var row = document.createElement('div');
        row.className = 'cloude-copy-row';
        row.appendChild(buildChip(termWrapper, item));

        if (item.kind === 'url' && isHttpUrl(item.value)) {
            var link = document.createElement('a');
            link.className = 'cloude-copy-open';
            link.href = item.value;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.textContent = tr('copy_output.open');
            link.setAttribute('aria-label', tr('copy_output.open.aria', { value: item.value }));
            link.title = tr('copy_output.open.title');
            row.appendChild(link);
        }
        return row;
    }

    function open(termWrapper) {
        close();
        if (!termWrapper || !termWrapper.term) return;

        var text = readRecentOutput(termWrapper.term);
        var items = window.OutputScan ? window.OutputScan.scan(text) : [];

        sheetEl = document.createElement('div');
        sheetEl.className = 'cloude-copy-sheet';
        sheetEl.setAttribute('role', 'dialog');
        sheetEl.setAttribute('aria-label', tr('copy_output.title'));

        var panel = document.createElement('div');
        panel.className = 'cloude-copy-sheet__panel';

        var head = document.createElement('div');
        head.className = 'cloude-copy-sheet__head';

        var title = document.createElement('span');
        title.className = 'cloude-copy-sheet__title';
        title.textContent = tr('copy_output.title');

        var closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.className = 'cloude-copy-sheet__close';
        closeBtn.setAttribute('aria-label', tr('modal.close'));
        closeBtn.textContent = 'x';
        closeBtn.addEventListener('click', close);

        head.appendChild(title);
        head.appendChild(closeBtn);
        panel.appendChild(head);

        if (items.length) {
            var chips = document.createElement('div');
            chips.className = 'cloude-copy-sheet__chips';
            items.forEach(function (item) {
                chips.appendChild(buildRow(termWrapper, item));
            });
            panel.appendChild(chips);
        } else {
            var none = document.createElement('p');
            none.className = 'cloude-copy-sheet__empty';
            none.textContent = tr('copy_output.none');
            panel.appendChild(none);
        }

        statusEl = document.createElement('p');
        statusEl.className = 'cloude-copy-status';
        statusEl.setAttribute('role', 'status');
        statusEl.setAttribute('aria-live', 'polite');
        statusEl.dataset.kind = 'info';
        statusEl.textContent = items.length
            ? tr('copy_output.status.items')
            : tr('copy_output.status.none');
        panel.appendChild(statusEl);

        var area = document.createElement('textarea');
        area.className = 'cloude-copy-sheet__text';
        area.setAttribute('readonly', '');
        area.setAttribute('aria-label', tr('copy_output.raw.aria'));
        area.value = text;
        panel.appendChild(area);
        textEl = area;

        var foot = document.createElement('div');
        foot.className = 'cloude-copy-sheet__foot';

        var copyAll = document.createElement('button');
        copyAll.type = 'button';
        copyAll.className = 'cloude-copy-sheet__action';
        copyAll.textContent = tr('copy_output.copy_all');
        copyAll.addEventListener('click', function () {
            copyAndReport(termWrapper, text, tr('copy_output.label.output'), copyAll);
        });

        var hint = document.createElement('span');
        hint.className = 'cloude-copy-sheet__hint';
        hint.textContent = window.CopyCompat.hasAsyncClipboard()
            ? tr('copy_output.hint.secure')
            : tr('copy_output.hint.insecure');

        foot.appendChild(copyAll);
        foot.appendChild(hint);
        panel.appendChild(foot);

        sheetEl.appendChild(panel);
        document.body.appendChild(sheetEl);

        sheetEl.addEventListener('click', function (e) {
            if (e.target === sheetEl) close();
        });
        onDocKey = function (e) {
            if (e.key === 'Escape') close();
        };
        document.addEventListener('keydown', onDocKey, true);
    }

    function close() {
        if (onDocKey) {
            document.removeEventListener('keydown', onDocKey, true);
            onDocKey = null;
        }
        if (sheetEl) {
            sheetEl.remove();
            sheetEl = null;
        }
        statusEl = null;
        textEl = null;
    }

    function wireButton(termWrapper, btn) {
        if (!btn || btn._copyOutputWired) return;
        btn._copyOutputWired = true;
        btn.addEventListener('click', function (e) {
            e.stopPropagation();
            if (sheetEl) {
                close();
            } else {
                open(termWrapper);
            }
        });
    }

    window.CopyOutput = {
        open: open,
        close: close,
        wireButton: wireButton,
        readRecentOutput: readRecentOutput,
        shortenForChip: shortenForChip,
        buildChip: buildChip,
        buildRow: buildRow,
        isHttpUrl: isHttpUrl
    };
})();
