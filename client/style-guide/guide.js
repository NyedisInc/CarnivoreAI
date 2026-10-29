(function () {
    'use strict';

    var BASE = '/static/style-guide/';
    var DEFAULT_THEME = 'carnivore';

    function getText(url) {
        return fetch(url, { cache: 'no-cache', credentials: 'same-origin' }).then(function (res) {
            if (!res.ok) throw new Error(url + ' answered HTTP ' + res.status);
            return res.text();
        });
    }

    function el(tag, cls, text) {
        var node = document.createElement(tag);
        if (cls) node.className = cls;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function filesBySection(registry) {
        var out = {};
        Object.keys(registry.files).sort().forEach(function (file) {
            var entry = registry.files[file];
            var groups = entry.classes_by_section
                ? entry.classes_by_section
                : (function () { var g = {}; g[entry.section] = entry.classes || []; return g; })();
            Object.keys(groups).forEach(function (section) {
                (out[section] = out[section] || []).push({ file: file, classes: groups[section] });
            });
        });
        return out;
    }

    function componentName(file) {
        var m = /([^/]+)\.svelte$/.exec(file);
        return m ? m[1] : null;
    }

    function coverageBlock(rows) {
        var wrap = el('details', 'sg-coverage');
        var count = rows.reduce(function (n, r) { return n + r.classes.length; }, 0);
        wrap.appendChild(el('summary', 'sg-coverage__summary',
            'files and classes this section covers: ' + rows.length + ' files, ' + count + ' classes'));
        var list = el('dl', 'sg-coverage__list');
        rows.forEach(function (row) {
            var name = componentName(row.file);
            var dt = el('dt', 'sg-coverage__file');
            dt.appendChild(el('code', null, row.file));
            if (name) dt.appendChild(el('span', 'sg-coverage__component', ' <' + name + '>'));
            list.appendChild(dt);
            var dd = el('dd', 'sg-coverage__classes');
            if (row.classes.length === 0) {
                dd.textContent = name ? 'no scoped style block: styled by the classes it borrows' : 'no classes';
            } else {
                row.classes.forEach(function (cls, i) {
                    if (i) dd.appendChild(document.createTextNode(' '));
                    dd.appendChild(el('code', null, '.' + cls));
                });
            }
            list.appendChild(dd);
        });
        wrap.appendChild(list);
        return wrap;
    }

    function buildToc(registry) {
        var toc = document.getElementById('sg-toc');
        var details = el('details', 'sg-toc__box');
        details.open = !window.matchMedia('(max-width: 899px)').matches;
        details.appendChild(el('summary', 'sg-toc__summary', 'sections'));
        var group = null;
        var list = null;
        registry.sections.forEach(function (section) {
            if (section.group !== group) {
                group = section.group;
                details.appendChild(el('p', 'sg-toc__group', group));
                list = el('ol', 'sg-toc__list');
                details.appendChild(list);
            }
            var item = el('li', 'sg-toc__item');
            var link = el('a', 'sg-toc__link', section.title);
            link.href = '#' + section.id;
            item.appendChild(link);
            list.appendChild(item);
        });
        toc.appendChild(details);
    }

    function buildIndex(registry, bySection) {
        var host = document.getElementById('sg-full-index');
        if (!host) return;
        host.textContent = '';
        registry.sections.forEach(function (section) {
            var rows = bySection[section.id];
            if (!rows) return;
            var h = el('h3', 'sg-h3');
            var a = el('a', null, section.title);
            a.href = '#' + section.id;
            h.appendChild(a);
            host.appendChild(h);
            var block = coverageBlock(rows);
            block.open = true;
            host.appendChild(block);
        });
    }

    function buildExclusions(registry) {
        var ex = document.getElementById('sg-exclusions');
        if (ex) {
            Object.keys(registry.excluded).forEach(function (prefix) {
                var li = el('li');
                li.appendChild(el('code', null, prefix));
                li.appendChild(document.createTextNode(': ' + registry.excluded[prefix]));
                ex.appendChild(li);
            });
        }
    }

    var loaded = null;

    function addPluginEntries(entries) {
        if (!loaded) return;
        var registry = loaded.registry;
        Object.keys(entries.rows || {}).forEach(function (file) { registry.files[file] = entries.rows[file]; });
        (entries.prose || []).forEach(function (item) {
            var section = registry.sections.filter(function (s) { return s.file === item.file; })[0];
            var host = section && document.getElementById(section.id);
            if (!host) return;
            var wrap = el('div', 'sg-plugin-prose');
            wrap.setAttribute('data-sg-plugin', item.plugin);
            wrap.innerHTML = item.html;
            host.insertBefore(wrap, host.querySelector(':scope > .sg-coverage'));
        });
        var bySection = filesBySection(registry);
        document.querySelectorAll('#sg-content > section > .sg-coverage').forEach(function (old) { old.remove(); });
        registry.sections.forEach(function (section) {
            var host = document.getElementById(section.id);
            if (host && bySection[section.id] && section.id !== 'index') host.appendChild(coverageBlock(bySection[section.id]));
        });
        buildIndex(registry, bySection);
    }

    var canvasCtx = null;

    function luminance(css) {
        if (!canvasCtx) {
            canvasCtx = document.createElement('canvas').getContext('2d', { willReadFrequently: true });
        }
        if (!canvasCtx) return null;
        canvasCtx.clearRect(0, 0, 1, 1);
        canvasCtx.fillStyle = '#000';
        canvasCtx.fillStyle = css;
        canvasCtx.fillRect(0, 0, 1, 1);
        var d = canvasCtx.getImageData(0, 0, 1, 1).data;
        var ch = [d[0], d[1], d[2]].map(function (v) {
            var c = v / 255;
            return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
        });
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
    }

    function ratio(a, b) {
        var la = luminance(a);
        var lb = luminance(b);
        if (la === null || lb === null) return null;
        var hi = Math.max(la, lb);
        var lo = Math.min(la, lb);
        return Math.round(((hi + 0.05) / (lo + 0.05)) * 100) / 100;
    }

    function resolved(name) {
        var probe = document.getElementById('sg-probe');
        if (!probe) {
            probe = el('span', 'sg-probe');
            probe.id = 'sg-probe';
            document.body.appendChild(probe);
        }
        probe.style.color = 'var(' + name + ')';
        return getComputedStyle(probe).color;
    }

    function paintTokens() {
        var rootStyle = getComputedStyle(document.documentElement);
        document.querySelectorAll('[data-sg-token]').forEach(function (row) {
            var name = row.getAttribute('data-sg-token');
            var raw = rootStyle.getPropertyValue(name).trim();
            var valueCell = row.querySelector('.sg-token__value');
            var swatch = row.querySelector('.sg-swatch');
            if (swatch) swatch.style.background = 'var(' + name + ')';
            if (valueCell) valueCell.textContent = swatch ? resolved(name) : raw;
            var on = row.getAttribute('data-sg-on');
            var ratioCell = row.querySelector('.sg-token__ratio');
            if (on && ratioCell) {
                var r = ratio(resolved(name), resolved(on));
                ratioCell.textContent = r === null ? 'n/a' : r + ':1';
                ratioCell.dataset.pass = r !== null && r >= 4.5 ? 'aa' : (r !== null && r >= 3 ? 'large' : 'fail');
            }
        });
    }

    function startThemes() {
        var select = document.getElementById('sg-theme-select');
        var status = document.getElementById('sg-theme-status');
        var params = new URLSearchParams(window.location.search);
        var wanted = params.get('theme') || DEFAULT_THEME;
        var themes = window.Themes;
        if (!themes || typeof themes.init !== 'function') {
            status.textContent = 'theme registry missing: showing the stylesheet defaults';
            return Promise.resolve();
        }
        return themes.init().then(function () {
            var all = themes.listAll();
            select.textContent = '';
            all.forEach(function (m) {
                var opt = el('option', null, m.name || m.id);
                opt.value = m.id;
                select.appendChild(opt);
            });
            var id = all.some(function (m) { return m.id === wanted; }) ? wanted : DEFAULT_THEME;
            apply(id);
            select.disabled = false;
            select.addEventListener('change', function () { apply(select.value); });
            status.textContent = all.length > 1
                ? all.length + ' themes'
                : 'only the default is listed: sign in to the app in this browser to list every theme';
        });

        function apply(id) {
            themes.applyTheme(id);
            select.value = id;
            document.documentElement.dataset.sgTheme = id;
            var next = new URLSearchParams(window.location.search);
            if (id === DEFAULT_THEME) next.delete('theme'); else next.set('theme', id);
            var query = next.toString();
            history.replaceState(null, '', window.location.pathname + (query ? '?' + query : '') + window.location.hash);
            paintTokens();
            document.dispatchEvent(new CustomEvent('style-guide:theme', { detail: { id: id } }));
        }
    }

    function fillRowMenuIcons() {
        var icons = window.SessionRowMenuIcons;
        if (!icons || typeof icons.svg !== 'function') return;
        document.querySelectorAll('[data-sg-row-icon]').forEach(function (slot) {
            slot.innerHTML = icons.svg(slot.getAttribute('data-sg-row-icon'), 12);
        });
    }

    function wireActions() {
        document.addEventListener('click', function (event) {
            var btn = event.target.closest && event.target.closest('[data-sg-action]');
            if (!btn) return;
            var action = btn.getAttribute('data-sg-action');
            var out = document.querySelector('[data-sg-result="' + action + '"]');
            if (action === 'text-prompt' && window.TextPromptModal) {
                window.TextPromptModal.open({
                    title: 'new group',
                    label: 'group name',
                    placeholder: 'music',
                    confirmLabel: 'create',
                }).then(function (value) {
                    if (out) out.textContent = value === null ? 'cancelled' : JSON.stringify(value);
                });
            }
        });
    }

    function boot() {
        var content = document.getElementById('sg-content');
        return getText(BASE + 'registry.json').then(function (text) {
            var registry = JSON.parse(text);
            var bySection = filesBySection(registry);
            return Promise.all(registry.sections.map(function (s) {
                return getText(BASE + 'sections/' + s.file);
            })).then(function (fragments) {
                registry.sections.forEach(function (section, i) {
                    var host = el('section', 'sg-section');
                    host.id = section.id;
                    host.setAttribute('data-sg-group', section.group);
                    host.innerHTML = fragments[i];
                    if (bySection[section.id] && section.id !== 'index') {
                        host.appendChild(coverageBlock(bySection[section.id]));
                    }
                    content.appendChild(host);
                });
                buildToc(registry);
                buildIndex(registry, bySection);
                buildExclusions(registry);
                loaded = { registry: registry };
            });
        }).then(function () {
            fillRowMenuIcons();
            wireActions();
            window.StyleGuideReady = true;
            document.dispatchEvent(new CustomEvent('style-guide:ready'));
            if (window.location.hash) {
                var target = document.getElementById(window.location.hash.slice(1));
                if (target) target.scrollIntoView();
            }
            return startThemes();
        }).catch(function (err) {
            var p = el('p', 'sg-error', 'the style guide could not load: ' + err.message);
            content.appendChild(p);
            document.documentElement.dataset.sgFailed = 'true';
            console.error('style guide:', err);
        });
    }

    window.StyleGuide = { ratio: ratio, resolved: resolved, paintTokens: paintTokens, addPluginEntries: addPluginEntries };
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', boot);
    } else {
        boot();
    }
})();
