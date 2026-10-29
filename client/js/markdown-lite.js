
console.log('[MarkdownLite Module] Loading...');

(function () {
    function escapeHtml(value) {
        return String(value == null ? '' : value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function isSafeUrl(url) {
        return !!(window.HttpUrl && window.HttpUrl.isHttpUrl(url));
    }

    function inline(text) {
        const codeStash = [];
        text = text.replace(/`([^`]+)`/g, (_, code) => {
            codeStash.push(code);
            return `\0CODE${codeStash.length - 1}\0`;
        });

        text = text.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (whole, label, url) => {
            if (!isSafeUrl(url)) return label;
            return `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`;
        });

        text = text.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
        text = text.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, '<em>$1</em>');

        text = text.replace(/\0CODE(\d+)\0/g, (_, i) => `<code>${codeStash[Number(i)]}</code>`);
        return text;
    }

    const TABLE_SEPARATOR = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;

    function splitRow(line) {
        return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());
    }

    function render(markdown) {
        const raw = String(markdown == null ? '' : markdown);

        const blockStash = [];
        const withoutFences = raw.replace(/```([a-zA-Z0-9_+-]*)\n?([\s\S]*?)```/g, (_, lang, code) => {
            const safeLang = escapeHtml(lang || '').replace(/[^a-zA-Z0-9_+-]/g, '');
            const html = `<pre class="config-editor-md-pre"><code${safeLang ? ` class="language-${safeLang}"` : ''}>${escapeHtml(code)}</code></pre>`;
            blockStash.push(html);
            return `\0BLOCK${blockStash.length - 1}\0`;
        });

        const escaped = escapeHtml(withoutFences);
        const lines = escaped.split('\n');
        const out = [];
        let listMode = null;
        let paragraph = [];
        let listItem = null;

        const flushParagraph = () => {
            if (paragraph.length) {
                out.push(`<p>${inline(paragraph.join(' '))}</p>`);
                paragraph = [];
            }
        };
        const flushItem = () => {
            if (listItem) {
                out.push(`<li>${inline(listItem.join(' '))}</li>`);
                listItem = null;
            }
        };
        const closeList = () => {
            flushItem();
            if (listMode) {
                out.push(listMode === 'ul' ? '</ul>' : '</ol>');
                listMode = null;
            }
        };

        for (let i = 0; i < lines.length; i++) {
            const line = lines[i];
            const blockToken = line.match(/^\0BLOCK(\d+)\0$/);
            if (blockToken) {
                flushParagraph();
                closeList();
                out.push(blockStash[Number(blockToken[1])]);
                continue;
            }

            const heading = line.match(/^(#{1,6})\s+(.*)$/);
            if (heading) {
                flushParagraph();
                closeList();
                const level = heading[1].length;
                out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
                continue;
            }

            if (/^(---|\*\*\*|___)\s*$/.test(line)) {
                flushParagraph();
                closeList();
                out.push('<hr>');
                continue;
            }

            if (line.includes('|') && i + 1 < lines.length && TABLE_SEPARATOR.test(lines[i + 1])) {
                flushParagraph();
                closeList();
                const rows = [splitRow(line)];
                let j = i + 2;
                while (j < lines.length && lines[j].includes('|') && lines[j].trim() !== '') rows.push(splitRow(lines[j++]));
                const cell = (tag, c) => `<${tag}>${inline(c)}</${tag}>`;
                const head = `<thead><tr>${rows[0].map((c) => cell('th', c)).join('')}</tr></thead>`;
                const body = rows.slice(1).map((r) => `<tr>${r.map((c) => cell('td', c)).join('')}</tr>`).join('');
                out.push(`<table>${head}<tbody>${body}</tbody></table>`);
                i = j - 1;
                continue;
            }

            const quote = line.match(/^&gt;\s?(.*)$/);
            if (quote) {
                flushParagraph();
                closeList();
                out.push(`<blockquote>${inline(quote[1])}</blockquote>`);
                continue;
            }

            const ulItem = line.match(/^[-*+]\s+(.*)$/);
            if (ulItem) {
                flushParagraph();
                if (listMode !== 'ul') { closeList(); out.push('<ul>'); listMode = 'ul'; }
                flushItem();
                listItem = [ulItem[1]];
                continue;
            }

            const olItem = line.match(/^\d+\.\s+(.*)$/);
            if (olItem) {
                flushParagraph();
                if (listMode !== 'ol') { closeList(); out.push('<ol>'); listMode = 'ol'; }
                flushItem();
                listItem = [olItem[1]];
                continue;
            }

            if (line.trim() === '') {
                flushParagraph();
                closeList();
                continue;
            }

            if (listItem) {
                listItem.push(line.trim());
                continue;
            }
            closeList();
            paragraph.push(line.trim());
        }
        flushParagraph();
        closeList();

        return out.join('\n');
    }

    window.MarkdownLite = { render };
    console.log('[MarkdownLite Module] Exported as window.MarkdownLite');
})();
