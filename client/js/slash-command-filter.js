
console.log('[SlashCommandFilter Module] Loading...');

class SlashCommandFilter {
    constructor() {
        this._items = [];
        this._visibleItems = [];
        this._activeIndex = -1;
    }

    index(root) {
        const items = root ? Array.from(root.querySelectorAll('.command-item')) : [];
        this._items = items.map(element => {
            const command = element.dataset.command || '';
            const descEl = element.querySelector('.command-description');
            const hasFull = element.dataset.description != null;
            const description = hasFull
                ? element.dataset.description
                : (descEl ? descEl.textContent : '');
            const searchText = (command + ' ' + description).toLowerCase();
            return { element, command, searchText };
        });
        this._visibleItems = this._items.slice();
        this._activeIndex = -1;
    }

    apply(query) {
        const q = (query || '').trim().toLowerCase();
        this.clearActiveHighlight();
        this._activeIndex = -1;
        this._visibleItems = [];

        const categoriesWithMatch = new Set();
        for (const item of this._items) {
            const matches = !q || item.searchText.includes(q);
            item.element.classList.toggle('filter-hidden', !matches);
            if (matches) {
                this._visibleItems.push(item);
                const categoryEl = item.element.closest('.command-category');
                if (categoryEl) categoriesWithMatch.add(categoryEl);
            }
        }

        const allCategories = new Set(this._items.map(i => i.element.closest('.command-category')).filter(Boolean));
        allCategories.forEach(categoryEl => {
            categoryEl.classList.toggle('filter-hidden', !categoriesWithMatch.has(categoryEl));
        });
    }

    clearActiveHighlight() {
        if (this._activeIndex >= 0 && this._visibleItems[this._activeIndex]) {
            this._visibleItems[this._activeIndex].element.classList.remove('keyboard-active');
        }
    }

    moveActive(delta) {
        if (this._visibleItems.length === 0) return;
        this.clearActiveHighlight();
        const next = this._activeIndex < 0
            ? (delta > 0 ? 0 : this._visibleItems.length - 1)
            : Math.min(Math.max(this._activeIndex + delta, 0), this._visibleItems.length - 1);
        this._activeIndex = next;
        const el = this._visibleItems[next].element;
        el.classList.add('keyboard-active');
        el.scrollIntoView({ block: 'nearest' });
    }

    getEnterTarget() {
        return this._activeIndex >= 0 ? this._visibleItems[this._activeIndex] : this._visibleItems[0];
    }
}

window.SlashCommandFilter = SlashCommandFilter;
console.log('[SlashCommandFilter Module] Exported as window.SlashCommandFilter');
