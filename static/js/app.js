'use strict';

// ── Utility ────────────────────────────────────────────────────────────────

async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const resp = await fetch(path, opts);
  if (resp.status === 401 && path !== '/config') {
    App.nav.go('login');
    throw new Error('Please login');
  }
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || data.message || `HTTP ${resp.status}`);
  return data;
}

function get(path, params) {
  if (!params) return api('GET', path);
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (Array.isArray(v)) v.forEach((item) => qs.append(k, item));
    else qs.append(k, v);
  }
  return api('GET', `${path}?${qs}`);
}
function post(path, body) {
  return api('POST', path, body);
}
function put(path, body) {
  return api('PUT', path, body);
}
function del(path) {
  return api('DELETE', path);
}

function el(id) {
  return document.getElementById(id);
}
function qs(sel, ctx) {
  return (ctx || document).querySelector(sel);
}

function debounce(fn, ms) {
  let t;
  return (...a) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
}

function escHtml(s) {
  // Decode any HTML entities the API may have pre-encoded (e.g. &#039; → ')
  // before re-escaping for safe insertion into HTML.
  const _d = document.createElement('textarea');
  _d.innerHTML = String(s ?? '');
  const decoded = _d.value;
  return decoded
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Layout helpers ─────────────────────────────────────────────────────────

const DESKTOP_PX = 900; // mobile/desktop breakpoint
const CHROME_H = 44 + 72 + 48; // header + nav + toolbar (px)
const CARD_MIN_W = 300;
const CARD_MIN_H = 160;
const CARD_GAP = 8;
const CARD_PAD = 8;

function isMobile() {
  return window.innerWidth < DESKTOP_PX;
}

function calcLayout(gridId) {
  const grid = el(gridId);
  const cols = Math.max(
    1,
    Math.floor((window.innerWidth - CARD_PAD * 2 + CARD_GAP) / (CARD_MIN_W + CARD_GAP))
  );
  const rows = Math.max(
    1,
    Math.floor((window.innerHeight - CHROME_H - CARD_PAD * 2 + CARD_GAP) / (CARD_MIN_H + CARD_GAP))
  );
  grid.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
  grid.style.gridTemplateRows = `repeat(${rows}, 1fr)`;
  return cols * rows;
}

function isOnShelf(ingId, ingredient) {
  return (
    State.shelfIds.has(ingId) || !!ingredient?.in_bar_shelf || !!Ingredients._shelfState.get(ingId)
  );
}

// ── Unit preference ────────────────────────────────────────────────────────

const UnitPref = {
  get() {
    return localStorage.getItem('sugar-rim-units') || 'oz';
  },
  set(u) {
    localStorage.setItem('sugar-rim-units', u);
  },

  toggle() {
    const next = this.get() === 'oz' ? 'ml' : 'oz';
    this.set(next);
    return next;
  },

  // Convert a single amount+unit pair to the preferred unit.
  // Returns { amount: string, unit: string }.
  convert(amount, unit) {
    if (!amount && amount !== 0) return { amount: amount ?? '', unit: unit || '' };
    const num = parseFloat(amount);
    if (isNaN(num)) return { amount: String(amount), unit: unit || '' };
    const u = (unit || '').toLowerCase().trim();
    const pref = this.get();

    if (pref === 'oz') {
      if (u === 'ml') return { amount: this._fmtOz(num / 30), unit: 'oz' };
      if (u === 'cl') return { amount: this._fmtOz((num * 10) / 30), unit: 'oz' };
    } else {
      if (u === 'oz') return { amount: String(Math.round(num * 30)), unit: 'ml' };
      if (u === 'cl') return { amount: String(Math.round(num * 10)), unit: 'ml' };
    }
    return { amount: String(amount), unit: unit || '' };
  },

  // Round to nearest ¼ oz and render with unicode fraction characters.
  _fmtOz(n) {
    const q = Math.round(n * 4);
    const whole = Math.floor(q / 4);
    const rem = q % 4;
    const fracs = ['', '¼', '½', '¾'];
    const frac = fracs[rem];
    if (whole === 0) return frac || '0';
    return frac ? `${whole} ${frac}` : String(whole);
  },
};

// ── Toast ──────────────────────────────────────────────────────────────────

const Toast = {
  _t: null,
  show(msg, isErr = false) {
    const t = el('toast');
    t.textContent = msg;
    t.className = 'toast' + (isErr ? ' err' : '');
    clearTimeout(this._t);
    this._t = setTimeout(() => {
      t.classList.add('hidden');
    }, 2800);
  },
  err(msg) {
    this.show(msg, true);
  },
};

// ── Modal ──────────────────────────────────────────────────────────────────

const Modal = {
  open(title, bodyHtml, footerHtml) {
    el('modal-title').textContent = title;
    el('modal-body').innerHTML = bodyHtml;
    el('modal-footer').innerHTML = footerHtml || '';
    el('modal-overlay').classList.remove('hidden');
  },
  close() {
    el('modal-overlay').classList.add('hidden');
  },
  closeOnBackdrop(e) {
    if (e.target === el('modal-overlay')) this.close();
  },
  body() {
    return el('modal-body');
  },
};

// ── Navigation ─────────────────────────────────────────────────────────────

const Nav = {
  _history: [],
  current: 'shelf',

  go(view) {
    if (this.current !== view) this._history.push(this.current);
    this._activate(view);
  },

  back() {
    const prev = this._history.pop() || 'cocktails';
    this._activate(prev);
  },

  _activate(view) {
    this.current = view;
    document.querySelectorAll('.view').forEach((v) => v.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach((b) => b.classList.remove('active'));
    const section = el(`view-${view}`);
    if (section) section.classList.add('active');
    const btn = qs(`[data-view="${view}"]`);
    if (btn) btn.classList.add('active');
  },
};

// ── Settings ───────────────────────────────────────────────────────────────

const Settings = {
  async load() {
    try {
      const cfg = await get('/config');
      el('cfg-url').value = cfg.api_url || '';
      if (cfg.is_logged_in) {
        await this._loadBars(cfg.bar_id);
        this.loadVersion();
      }
    } catch (e) {
      /* silent */
    }
    this._syncUnitButtons();
  },

  setUnit(u) {
    UnitPref.set(u);
    this._syncUnitButtons();
    el('unit-toggle-btn').textContent = u;
    if (App.cocktails.currentData) App.cocktails._renderDetail(App.cocktails.currentData);
  },

  _syncUnitButtons() {
    const u = UnitPref.get();
    el('settings-unit-oz').classList.toggle('shelf-active', u === 'oz');
    el('settings-unit-ml').classList.toggle('shelf-active', u === 'ml');
  },

  async loadVersion() {
    try {
      const d = await get('/api/server/version');
      el('server-version').textContent = `API Version: ${d.data?.version || 'Unknown'}`;
    } catch (e) {
      el('server-version').textContent = 'API Version: Error';
    }
  },

  async saveUrl() {
    const url = el('cfg-url').value.trim();
    const msg = el('cfg-message');
    if (!url) {
      msg.textContent = '✗ URL is required';
      msg.className = 'cfg-status err';
      return;
    }
    try {
      await post('/config', { api_url: url });
      msg.textContent = '✓ Saved';
      msg.className = 'cfg-status ok';
      this.loadVersion();
    } catch (e) {
      msg.textContent = '✗ ' + e.message;
      msg.className = 'cfg-status err';
    }
  },

  async _loadBars(currentBarId) {
    const sel = el('cfg-bar');
    sel.innerHTML = '<option value="">Loading…</option>';
    try {
      const d = await get('/api/bars');
      const bars = d.data || [];
      if (!bars.length) {
        sel.innerHTML = '<option value="">No bars found</option>';
        return;
      }
      sel.innerHTML = bars
        .map(
          (b) =>
            `<option value="${b.id}" ${String(b.id) === String(currentBarId) ? 'selected' : ''}>${escHtml(b.name)}</option>`
        )
        .join('');
      // Auto-save if only one bar and none selected yet
      if (bars.length === 1 && !currentBarId) {
        await post('/config', { bar_id: bars[0].id });
        Toast.show(`Bar set to "${bars[0].name}"`);
      }
    } catch (e) {
      sel.innerHTML = '<option value="">Could not load bars</option>';
    }
  },

  async saveBar() {
    const bar_id = el('cfg-bar').value;
    const msg = el('cfg-bar-message');
    if (!bar_id) {
      Toast.err('Select a bar first');
      return;
    }
    try {
      await post('/config', { bar_id });
      msg.textContent = '✓ Bar saved';
      msg.className = 'cfg-status ok';
      Toast.show('Active bar updated');
    } catch (e) {
      msg.textContent = '✗ ' + e.message;
      msg.className = 'cfg-status err';
    }
  },
};

// ── App state ──────────────────────────────────────────────────────────────

const State = {
  profile: null,
  shelfIds: new Set(),

  async loadProfile() {
    try {
      const resp = await fetch('/api/profile');
      if (resp.ok) {
        const d = await resp.json();
        this.profile = d.data;
        el('header-subtitle').textContent = this.profile?.name || '';
      }
      // 403 means token lacks ability:* — non-fatal, just skip name display
    } catch (e) {
      /* silent */
    }
  },

  async loadShelfIds() {
    try {
      const d = await get('/api/shelf');
      this.shelfIds = new Set((d.data || []).map((i) => i.id));
    } catch (e) {
      this.shelfIds = new Set();
    }
  },
};

// ── Shelf ──────────────────────────────────────────────────────────────────

const Shelf = {
  items: [],
  filtered: [],

  async load() {
    const grid = el('shelf-list');
    const empty = el('shelf-empty');
    grid.innerHTML = '<div class="loading-row"><div class="spinner"></div></div>';
    try {
      const d = await get('/api/shelf');
      this.items = d.data || [];
      State.shelfIds = new Set(this.items.map((i) => i.id));
      this.render(this.items);
    } catch (e) {
      grid.innerHTML = '';
      empty.classList.remove('hidden');
      empty.querySelector('p').textContent = e.message;
    }
  },

  render(items) {
    const grid = el('shelf-list');
    const empty = el('shelf-empty');
    if (!items.length) {
      grid.innerHTML = '';
      empty.classList.remove('hidden');
      return;
    }
    empty.classList.add('hidden');
    grid.innerHTML = items
      .map((i) => {
        const thumb = i.images?.[0]
          ? `<img src="/api/images/${i.images[0].id}/thumb" class="card-thumb">`
          : '';
        return `<div class="card shelf-card row-layout">
        ${thumb}
        <div class="card-content">
          <div class="card-name">${escHtml(i.name)}</div>
        </div>
        <button class="remove-btn" style="position:static;margin-left:auto;" onclick="App.shelf.remove(${i.id})" title="Remove from shelf">✕</button>
      </div>`;
      })
      .join('');
  },

  filter(q) {
    const lq = q.toLowerCase();
    this.render(
      q
        ? this.items.filter((i) => (i.name || i.ingredient?.name || '').toLowerCase().includes(lq))
        : this.items
    );
  },

  async remove(id) {
    try {
      await post('/api/shelf/batch-delete', { ingredients: [id] });
      State.shelfIds.delete(id);
      this.items = this.items.filter((i) => i.id !== id);
      this.render(this.items);
      Toast.show('Removed from shelf');
    } catch (e) {
      Toast.err(e.message);
    }
  },

  showAddModal() {
    Modal.open(
      'Add to Shelf',
      `<div class="form-group">
        <label class="form-label">Search ingredient</label>
        <input class="text-input" id="shelf-add-search" placeholder="Type to search…">
        <div id="shelf-add-results" style="margin-top:8px;display:flex;flex-direction:column;gap:6px;max-height:260px;overflow-y:auto"></div>
      </div>`,
      `<button class="btn btn-ghost" onclick="App.modal.close()">Cancel</button>`
    );
    const inp = el('shelf-add-search');
    inp.addEventListener(
      'input',
      debounce(() => this._searchForAdd(inp.value), 300)
    );
    inp.focus();
  },

  async _searchForAdd(q) {
    if (q.length < 2) return;
    const res = el('shelf-add-results');
    res.innerHTML = '<div class="spinner"></div>';
    try {
      const d = await get('/api/ingredients', { 'filter[name]': q, per_page: 20 });
      const items = d.data || [];
      if (!items.length) {
        res.innerHTML = '<span style="color:var(--text-dim);font-size:.85rem">No results</span>';
        return;
      }
      res.innerHTML = items
        .map((i) => {
          const onShelf = State.shelfIds.has(i.id);
          return `<button class="card" style="min-height:auto;padding:8px 12px;flex-direction:row;align-items:center;gap:8px;cursor:${onShelf ? 'default' : 'pointer'};opacity:${onShelf ? '.5' : '1'}"
          ${onShelf ? 'disabled' : `onclick="App.shelf.addById(${i.id}, '${escHtml(i.name)}')"`}>
          <span style="flex:1;font-size:.88rem">${escHtml(i.name)}</span>
          ${onShelf ? '<span style="color:var(--accent2);font-size:.75rem">on shelf</span>' : ''}
        </button>`;
        })
        .join('');
    } catch (e) {
      res.innerHTML = `<span style="color:#f87171;font-size:.85rem">${escHtml(e.message)}</span>`;
    }
  },

  async addById(id, name) {
    try {
      await post('/api/shelf/batch', { ingredients: [id] });
      State.shelfIds.add(id);
      Toast.show(`Added ${name} to shelf`);
      Modal.close();
      this.load();
    } catch (e) {
      Toast.err(e.message);
    }
  },
};

// ── Cocktails ──────────────────────────────────────────────────────────────

const Cocktails = {
  page: 1,
  lastMeta: null,
  shelfOnly: false,
  sortBy: 'name',
  sortDir: 'asc',
  query: '',
  ingredientFilter: [],
  tagFilter: [],
  _allTags: [],
  _acHighlight: -1,
  currentId: null,
  currentData: null,
  _servings: 1,
  _cache: new Map(),
  _loadingMore: false,

  toggleShelf() {
    this.shelfOnly = !this.shelfOnly;
    el('shelf-only-toggle').classList.toggle('shelf-active', this.shelfOnly);
    el('header-shelf-toggle').classList.toggle('shelf-active', this.shelfOnly);
    this.load(1);
  },

  setSort(value) {
    const [field, dir] = value.split('-');
    this.sortBy = field;
    this.sortDir = dir;
    this.load(1);
  },

  addIngredient(ing) {
    if (this.ingredientFilter.some((f) => f.id === ing.id)) return;
    this.ingredientFilter.push(ing);
    this._renderChips();
    this._syncClearBtn();
    this.load(1);
  },

  removeIngredient(id) {
    this.ingredientFilter = this.ingredientFilter.filter((f) => f.id !== id);
    this._renderChips();
    this._syncClearBtn();
    this.load(1);
  },

  _renderChips() {
    el('ing-chips').innerHTML = this.ingredientFilter
      .map(
        (ing) =>
          `<span class="ing-chip">${escHtml(ing.name)}<button class="ing-chip-remove" onclick="Cocktails.removeIngredient(${ing.id})" title="Remove">×</button></span>`
      )
      .join('');
  },

  _syncClearBtn() {
    const hasFilters = this.ingredientFilter.length > 0 || this.tagFilter.length > 0;
    el('filter-clear-btn').classList.toggle('hidden', !hasFilters);
  },

  clearAllFilters() {
    this.ingredientFilter = [];
    this.tagFilter = [];
    this._renderChips();
    this._renderTagChips();
    this._syncClearBtn();
    this._syncTagBtn();
    this.load(1);
  },

  _selectIngredient(ing) {
    el('ing-filter-input').value = '';
    el('ing-autocomplete').classList.add('hidden');
    this._acHighlight = -1;
    this.addIngredient(ing);
  },

  async toggleTagModal() {
    if (!this._allTags.length) {
      try {
        const d = await get('/api/tags');
        const sorted = (d.data || []).sort((a, b) => a.name.localeCompare(b.name));
        const seen = new Set();
        this._allTags = sorted.filter((t) => {
          const key = t.name.toLowerCase();
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        });
      } catch (e) {
        Toast.show('Could not load tags: ' + e.message);
        return;
      }
    }
    const chips = this._allTags
      .map((t) => {
        const active = this.tagFilter.some((f) => f.id === t.id);
        return `<button class="tag-chip-toggle${active ? ' active' : ''}" onclick="Cocktails._toggleTag(${t.id})">${escHtml(t.name)}</button>`;
      })
      .join('');
    App.modal.open(
      'Filter by Style / Tag',
      `<div class="tag-chip-grid">${chips}</div>`,
      `<button class="btn btn-ghost btn-wide" onclick="Cocktails._clearTags(); App.modal.close()">Clear all</button>
       <button class="btn btn-primary btn-wide" onclick="App.modal.close()">Done</button>`
    );
  },

  _toggleTag(id) {
    const idx = this.tagFilter.findIndex((f) => f.id === id);
    if (idx >= 0) {
      this.tagFilter.splice(idx, 1);
    } else {
      const tag = this._allTags.find((t) => t.id === id);
      if (tag) this.tagFilter.push(tag);
    }
    // update chip state in-modal without closing
    document.querySelectorAll('.tag-chip-toggle').forEach((btn) => {
      const btnId = parseInt(btn.getAttribute('onclick').match(/\d+/)[0]);
      btn.classList.toggle(
        'active',
        this.tagFilter.some((f) => f.id === btnId)
      );
    });
    this._renderTagChips();
    this._syncTagBtn();
    this.load(1);
  },

  _renderTagChips() {
    el('tag-chips').innerHTML = this.tagFilter
      .map(
        (t) =>
          `<span class="tag-chip">${escHtml(t.name)}<button class="ing-chip-remove" onclick="Cocktails._toggleTag(${t.id})" title="Remove">×</button></span>`
      )
      .join('');
    this._syncClearBtn();
  },

  _clearTags() {
    this.tagFilter = [];
    this._renderTagChips();
    this._syncTagBtn();
    this.load(1);
  },

  _syncTagBtn() {
    const btn = el('tag-filter-btn');
    if (!btn) return;
    const n = this.tagFilter.length;
    btn.textContent = n ? `Tags (${n})` : 'Tags';
    btn.classList.toggle('shelf-active', n > 0);
  },

  _buildParams(page, perPage) {
    const params = { page, per_page: perPage };
    if (this.query) params['filter[name]'] = this.query;
    if (this.shelfOnly) params['filter[on_shelf]'] = true;
    if (this.ingredientFilter.length) {
      params['filter[ingredient_name][]'] = this.ingredientFilter.map((i) => i.name);
    }
    if (this.tagFilter.length) {
      params['filter[tag_id][]'] = this.tagFilter.map((t) => t.id);
    }
    if (this.sortBy === 'rating') {
      params['sort'] = this.sortDir === 'desc' ? '-average_rating,name' : 'average_rating,name';
    } else if (this.sortBy === 'date') {
      params['sort'] = this.sortDir === 'desc' ? '-created_at' : 'created_at';
    } else {
      params['sort'] = this.sortDir === 'desc' ? '-name' : 'name';
    }
    return params;
  },

  async load(page = 1) {
    this.page = page;
    const grid = el('cocktail-list');
    const empty = el('cocktail-empty');
    grid.innerHTML = '<div class="loading-row"><div class="spinner"></div></div>';
    const perPage = isMobile() ? 30 : calcLayout('cocktail-list');
    const params = this._buildParams(page, perPage);
    try {
      const d = await get('/api/cocktails', params);
      const items = d.data || [];
      this.lastMeta = d.meta;
      if (!items.length) {
        grid.innerHTML = '';
        empty.classList.remove('hidden');
        this._renderPagination();
        return;
      }
      empty.classList.add('hidden');
      grid.innerHTML = items.map((c) => this._card(c)).join('');
      this._renderPagination();
      this._enrichCards(items);
    } catch (e) {
      grid.innerHTML = '';
      empty.classList.remove('hidden');
      empty.querySelector('p').textContent = e.message;
    }
  },

  _card(c) {
    const fav = c.is_favorited ? '<span class="card-fav-badge">★</span>' : '';
    let ingFull;
    if (c.ingredients?.length) {
      ingFull = c.ingredients
        .filter((i) => !i.optional)
        .map((i) => escHtml(i.ingredient?.name || ''))
        .filter(Boolean)
        .join(' · ');
    } else {
      ingFull = (c.short_ingredients || []).map(escHtml).join(' · ');
    }
    const ingNames =
      ingFull.length > 100 ? ingFull.slice(0, 100).replace(/ ·[^·]*$/, '') + ' …' : ingFull;
    return `<div class="card cocktail-card" data-id="${c.id}" onclick="App.cocktails.open(${c.id})">
      <div class="cocktail-thumb-wrap">
        <div class="card-thumb-slot" id="cthumb-${c.id}"></div>
        ${fav}
      </div>
      <div class="cocktail-card-body">
        <div class="card-name">${escHtml(c.name)}</div>
        ${ingNames ? `<div class="card-ings">${ingNames}</div>` : ''}
        <div class="card-rating" id="crating-${c.id}"></div>
      </div>
    </div>`;
  },

  async _enrichCards(items) {
    await Promise.all(
      items.map(async (c) => {
        try {
          const cached = this._cache.get(c.id);
          const data = cached ?? (await get(`/api/cocktails/${c.id}`)).data;
          if (!cached) this._cache.set(c.id, data);

          const thumbSlot = el(`cthumb-${c.id}`);
          if (thumbSlot) {
            if (data.images?.[0]) {
              const img = document.createElement('img');
              img.src = `/api/images/${data.images[0].id}/thumb`;
              img.className = 'card-thumb';
              img.loading = 'lazy';
              thumbSlot.replaceWith(img);
            } else {
              thumbSlot.className = 'card-thumb-empty';
            }
          }

          const ratingSlot = el(`crating-${c.id}`);
          if (ratingSlot && data.rating?.average > 0) {
            const avg = data.rating.average;
            const full = Math.round(avg);
            ratingSlot.innerHTML =
              `<span class="rating-stars">${'★'.repeat(full)}${'☆'.repeat(5 - full)}</span>` +
              `<span class="rating-num">${avg.toFixed(1)}</span>`;
          }
        } catch (e) {
          /* silent — card just stays without image/rating */
        }
      })
    );
  },

  _renderPagination() {
    if (isMobile()) return;
    const m = this.lastMeta;
    const bar = el('cocktail-pagination');
    if (!m || m.last_page <= 1) {
      bar.innerHTML = '';
      return;
    }
    const prev =
      m.current_page > 1
        ? `<button class="btn btn-ghost" onclick="App.cocktails.load(${m.current_page - 1})">‹ Prev</button>`
        : '<button class="btn btn-ghost" style="visibility:hidden">‹ Prev</button>';
    const next =
      m.current_page < m.last_page
        ? `<button class="btn btn-ghost" onclick="App.cocktails.load(${m.current_page + 1})">Next ›</button>`
        : '<button class="btn btn-ghost" style="visibility:hidden">Next ›</button>';
    bar.innerHTML = `${prev}<span>${m.current_page} / ${m.last_page}</span>${next}`;
  },

  async _maybeLoadMore() {
    const m = this.lastMeta;
    if (!m || m.current_page >= m.last_page || this._loadingMore) return;
    this._loadingMore = true;
    try {
      const page = m.current_page + 1;
      const params = this._buildParams(page, 30);
      const d = await get('/api/cocktails', params);
      const items = d.data || [];
      this.lastMeta = d.meta;
      if (items.length) {
        el('cocktail-list').insertAdjacentHTML(
          'beforeend',
          items.map((c) => this._card(c)).join('')
        );
        this._enrichCards(items);
      }
    } catch (e) {
      /* silent */
    } finally {
      this._loadingMore = false;
    }
  },

  async open(id) {
    this.currentId = id;
    this._servings = 1;
    Nav.go('detail');
    el('detail-title').textContent = '…';

    // Show cached data immediately while we refresh in background
    const cached = this._cache.get(id);
    if (cached) {
      this.currentData = cached;
      this._renderDetail(cached);
    } else {
      el('detail-body').innerHTML = '<div class="loading-row"><div class="spinner"></div></div>';
    }

    // Always re-fetch cocktail + shelf in parallel for accurate availability
    try {
      const [, cocktailResp] = await Promise.all([
        State.loadShelfIds(),
        get(`/api/cocktails/${id}`),
      ]);
      const data = cocktailResp.data;
      this.currentData = data;
      this._cache.set(id, data);
      if (this.currentId === id) this._renderDetail(data);
    } catch (e) {
      if (!cached)
        el('detail-body').innerHTML = `<p style="color:#f87171">${escHtml(e.message)}</p>`;
    }
  },

  toggleUnit() {
    UnitPref.toggle();
    el('unit-toggle-btn').textContent = UnitPref.get();
    if (this.currentData) this._renderDetail(this.currentData);
  },

  setServings(n) {
    if (n < 1) return;
    this._servings = n;
    if (this.currentData) this._renderDetail(this.currentData);
  },

  _renderDetail(c) {
    el('detail-title').textContent = c.name;
    el('detail-fav-btn').textContent = c.is_favorited ? '★' : '☆';
    el('unit-toggle-btn').textContent = UnitPref.get();

    const s = this._servings;
    const stepper = `<div class="servings-stepper">
      <button class="servings-btn" onclick="App.cocktails.setServings(${s - 1})" ${s <= 1 ? 'disabled' : ''}>−</button>
      <span class="servings-count">${s}×</span>
      <button class="servings-btn" onclick="App.cocktails.setServings(${s + 1})">+</button>
    </div>`;

    const ings = (c.ingredients || [])
      .map((i) => {
        const ingId = i.ingredient_id ?? i.ingredient?.id;
        const onShelf = isOnShelf(ingId, i.ingredient);
        const dot = `<span class="ing-dot ${onShelf ? 'ing-dot-on' : 'ing-dot-off'}" title="${onShelf ? 'On shelf' : 'Not on shelf'}"></span>`;
        const scaled =
          i.amount && !isNaN(parseFloat(i.amount)) ? parseFloat(i.amount) * s : i.amount;
        const { amount: amt, unit: unt } = UnitPref.convert(scaled, i.units);
        const amtStr = i.amount ? `${amt} ${unt}`.trim() : '';
        const note = i.note ? `<span class="ing-note">${escHtml(i.note)}</span>` : '';
        return `<div class="ingredient-row">
        ${dot}
        <span class="ing-amount">${escHtml(amtStr)}</span>
        <span class="ing-name">${escHtml(i.name || i.ingredient?.name || '')}${note}</span>
      </div>`;
      })
      .join('');

    const tags = (c.tags || [])
      .map((t) => `<span class="tag">${escHtml(t.name || t)}</span>`)
      .join('');

    const userRating = c.rating?.user_rating ?? 0;
    const avgRating = c.rating?.average ?? 0;
    const displayStars = userRating || Math.round(avgRating);
    const starsHtml = [1, 2, 3, 4, 5]
      .map(
        (n) =>
          `<span class="detail-rating-star ${n <= displayStars ? 'active' : ''}" onclick="App.cocktails.rate(${c.id},${n})">${n <= displayStars ? '★' : '☆'}</span>`
      )
      .join('');

    const hasImage = !!c.images?.[0];

    const metaSection = `
      <div class="detail-section" style="margin-bottom:0">
        <h3>Description</h3>
        <div class="detail-meta">
          ${c.glass ? `<span><strong>Glass:</strong> ${escHtml(c.glass.name || c.glass)}</span>` : ''}
          ${c.method ? `<span><strong>Method:</strong> ${escHtml(c.method.name || c.method)}</span>` : ''}
          ${c.abv ? `<span><strong>ABV:</strong> ${escHtml(c.abv)}%</span>` : ''}
          <span><strong>Rating:</strong> <span class="meta-stars">${starsHtml}${avgRating > 0 ? `<span class="detail-rating-avg">avg ${avgRating.toFixed(1)}</span>` : ''}</span></span>
        </div>
        ${tags ? `<div class="card-tags">${tags}</div>` : ''}
        ${c.description ? `<p class="detail-instructions" style="margin-top:12px">${escHtml(c.description)}</p>` : ''}
      </div>`;

    const ingsSection = `
      <div class="detail-section">
        <div class="detail-section-header"><h3>Ingredients</h3>${stepper}</div>
        ${ings || '<p style="color:var(--text-dim)">None listed</p>'}
      </div>`;

    const topContent = hasImage
      ? `<div class="detail-main">
           <img class="detail-image-main" src="/api/images/${c.images[0].id}/thumb" alt="${escHtml(c.name)}">
           <div class="detail-main-right">${metaSection}${ingsSection}</div>
         </div>`
      : `${metaSection}${ingsSection}`;

    el('detail-body').innerHTML = `
      ${topContent}
      ${c.instructions ? `<div class="detail-section"><h3>Instructions</h3><p class="detail-instructions">${escHtml(c.instructions)}</p></div>` : ''}
      ${c.garnish ? `<div class="detail-section"><h3>Garnish</h3><p class="detail-instructions">${escHtml(c.garnish)}</p></div>` : ''}
    `;
  },

  async toggleFav() {
    if (!this.currentId) return;
    try {
      await post(`/api/cocktails/${this.currentId}/toggle-favorite`);
      const btn = el('detail-fav-btn');
      const nowFav = btn.textContent === '☆';
      btn.textContent = nowFav ? '★' : '☆';
      if (this.currentData) this.currentData.is_favorited = nowFav;
      if (this._cache.has(this.currentId)) this._cache.get(this.currentId).is_favorited = nowFav;
      const wrap = qs(`.cocktail-card[data-id="${this.currentId}"] .cocktail-thumb-wrap`);
      if (wrap) {
        const badge = wrap.querySelector('.card-fav-badge');
        if (nowFav && !badge) {
          const b = document.createElement('span');
          b.className = 'card-fav-badge';
          b.textContent = '★';
          wrap.appendChild(b);
        } else if (!nowFav && badge) {
          badge.remove();
        }
      }
      Toast.show(nowFav ? 'Added to favorites' : 'Removed from favorites');
    } catch (e) {
      Toast.err(e.message);
    }
  },

  async rate(id, stars) {
    if ((this.currentData?.rating?.user_rating ?? 0) === stars) {
      return this.clearRate(id);
    }
    try {
      await post(`/api/cocktails/${id}/ratings`, { rating: stars });
      await this._refreshRating(id, stars);
      Toast.show(`Rated ${stars} ★`);
    } catch (e) {
      Toast.err(e.message);
    }
  },

  async clearRate(id) {
    try {
      await del(`/api/cocktails/${id}/ratings`);
      await this._refreshRating(id, 0);
      Toast.show('Rating cleared');
    } catch (e) {
      Toast.err(e.message);
    }
  },

  async _refreshRating(id, userRating) {
    const fresh = await get(`/api/cocktails/${id}`);
    const rating = fresh.data?.rating || {};
    rating.user_rating = userRating;
    if (this.currentData) this.currentData.rating = rating;
    if (this._cache.has(id)) this._cache.get(id).rating = rating;

    const avgRating = rating.average ?? 0;
    const displayStars = userRating || Math.round(avgRating);
    document.querySelectorAll('#detail-body .detail-rating-star').forEach((s, i) => {
      const filled = i + 1 <= displayStars;
      s.textContent = filled ? '★' : '☆';
      s.classList.toggle('active', filled);
    });
    const avgEl = qs('#detail-body .detail-rating-avg');
    if (avgEl) {
      avgEl.textContent = avgRating > 0 ? `avg ${avgRating.toFixed(1)}` : '';
    } else if (avgRating > 0) {
      qs('#detail-body .detail-rating-row')?.insertAdjacentHTML(
        'beforeend',
        `<span class="detail-rating-avg">avg ${avgRating.toFixed(1)}</span>`
      );
    }
    const ratingSlot = el(`crating-${id}`);
    if (ratingSlot) {
      const cardStars = Math.round(avgRating);
      ratingSlot.innerHTML =
        cardStars > 0
          ? `<span class="rating-stars">${'★'.repeat(cardStars)}${'☆'.repeat(5 - cardStars)}</span><span class="rating-num">${avgRating.toFixed(1)}</span>`
          : '';
    }
  },

  _formIngredients: [],
  _glasses: null,
  _methods: null,

  editCurrent() {
    if (this.currentData) this.showEdit(this.currentData);
  },

  showCreate() {
    this._showForm(null);
  },

  showEdit(c) {
    this._showForm(c);
  },

  async _showForm(c) {
    Modal.open(
      c ? `Edit: ${c.name}` : 'New Cocktail',
      '<div class="loading-row"><div class="spinner"></div></div>',
      ''
    );

    if (!this._glasses) {
      try {
        const d = await get('/api/glasses');
        this._glasses = d.data || [];
      } catch {
        this._glasses = [];
      }
    }
    if (!this._methods) {
      try {
        const d = await get('/api/methods');
        this._methods = d.data || [];
      } catch {
        this._methods = [];
      }
    }

    this._formIngredients = (c?.ingredients || []).map((i, idx) => ({
      ingredient_id: i.ingredient?.id,
      name: i.ingredient?.name || i.name || '',
      amount: i.amount != null ? String(i.amount) : '',
      units: i.units || '',
      note: i.note || '',
      optional: !!i.optional,
      sort: i.sort ?? idx + 1,
    }));

    const title = c ? `Edit: ${c.name}` : 'New Cocktail';
    Modal.open(
      title,
      `<div class="form-group"><label class="form-label">Name *</label>
        <input class="text-input" id="cf-name" value="${escHtml(c?.name || '')}" placeholder="Cocktail name"></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Glass</label>
          <select class="text-input" id="cf-glass">
            <option value="">— none —</option>
            ${this._glasses.map((g) => `<option value="${g.id}" ${c?.glass?.id === g.id ? 'selected' : ''}>${escHtml(g.name)}</option>`).join('')}
          </select></div>
        <div class="form-group"><label class="form-label">Method</label>
          <select class="text-input" id="cf-method">
            <option value="">— none —</option>
            ${this._methods.map((m) => `<option value="${m.id}" ${c?.method?.id === m.id ? 'selected' : ''}>${escHtml(m.name)}</option>`).join('')}
          </select></div>
      </div>
      <div class="form-group"><label class="form-label">Instructions</label>
        <textarea class="text-input" id="cf-instructions">${escHtml(c?.instructions || '')}</textarea></div>
      <div class="form-group"><label class="form-label">Garnish</label>
        <input class="text-input" id="cf-garnish" value="${escHtml(c?.garnish || '')}" placeholder="Optional garnish"></div>
      <div class="form-group"><label class="form-label">Tags (comma-separated)</label>
        <input class="text-input" id="cf-tags" value="${(c?.tags || []).map((t) => t.name || t).join(', ')}"></div>
      <datalist id="cf-units-list">
        <option value="oz"></option><option value="ml"></option><option value="cl"></option>
        <option value="dashes"></option><option value="barspoon"></option>
        <option value="drops"></option><option value="topup"></option><option value="leaves"></option>
      </datalist>
      <div class="form-group">
        <label class="form-label">Ingredients</label>
        <div id="cf-ing-list"></div>
        <div class="cf-ing-search-wrap">
          <input type="text" id="cf-ing-search" class="text-input" placeholder="Search to add ingredient…" autocomplete="off">
          <ul id="cf-ing-ac" class="autocomplete-list hidden"></ul>
        </div>
      </div>`,
      `${c ? `<button class="btn btn-ghost" style="color:var(--accent);margin-right:auto" onclick="App.modal.close();App.cocktails.deleteCurrent()">Delete</button>` : ''}
       <button class="btn btn-ghost" onclick="App.modal.close()">Cancel</button>
       <button class="btn btn-primary" onclick="App.cocktails._submitForm(${c?.id || 'null'})">${c ? 'Save' : 'Create'}</button>`
    );
    this._renderFormIngredients();
    this._wireFormIngSearch();
    el('cf-name').focus();
  },

  _renderFormIngredients() {
    const list = el('cf-ing-list');
    if (!list) return;
    if (!this._formIngredients.length) {
      list.innerHTML = '<p class="cf-ing-empty">No ingredients yet — search below to add.</p>';
      return;
    }
    list.innerHTML = this._formIngredients
      .map(
        (ing) => `
      <div class="cf-ing-row" data-ingid="${ing.ingredient_id}">
        <div class="cf-ing-row-name">
          <span class="cf-ing-handle material-symbols-rounded">drag_indicator</span>
          <span class="cf-ing-name-text">${escHtml(ing.name)}</span>
          <button class="cf-ing-remove" onclick="App.cocktails._removeFormIng(${ing.ingredient_id})" title="Remove">×</button>
        </div>
        <div class="cf-ing-row-fields">
          <input class="text-input cf-ing-amount" value="${escHtml(ing.amount)}" placeholder="Amt">
          <input class="text-input cf-ing-unit"   value="${escHtml(ing.units)}"  placeholder="Unit" list="cf-units-list">
          <input class="text-input cf-ing-note"   value="${escHtml(ing.note)}"   placeholder="Note">
          <label class="cf-ing-opt-label"><input class="cf-ing-opt-check" type="checkbox" ${ing.optional ? 'checked' : ''}> Opt</label>
        </div>
      </div>`
      )
      .join('');

    if (typeof Sortable !== 'undefined') {
      Sortable.create(list, {
        handle: '.cf-ing-handle',
        animation: 150,
        onEnd: () => {
          this._collectFormIngData();
          const newOrder = [...list.querySelectorAll('.cf-ing-row')].map((row) =>
            this._formIngredients.find((f) => f.ingredient_id === parseInt(row.dataset.ingid))
          );
          this._formIngredients = newOrder;
        },
      });
    }
  },

  _collectFormIngData() {
    document.querySelectorAll('#cf-ing-list .cf-ing-row').forEach((row) => {
      const ing = this._formIngredients.find(
        (f) => f.ingredient_id === parseInt(row.dataset.ingid)
      );
      if (!ing) return;
      ing.amount = row.querySelector('.cf-ing-amount').value.trim();
      ing.units = row.querySelector('.cf-ing-unit').value.trim();
      ing.note = row.querySelector('.cf-ing-note').value.trim();
      ing.optional = row.querySelector('.cf-ing-opt-check').checked;
    });
  },

  _addFormIng(ing) {
    this._collectFormIngData();
    if (this._formIngredients.some((f) => f.ingredient_id === ing.id)) return;
    this._formIngredients.push({
      ingredient_id: ing.id,
      name: ing.name,
      amount: '',
      units: 'oz',
      note: '',
      optional: false,
    });
    this._renderFormIngredients();
    el('cf-ing-search').value = '';
    el('cf-ing-ac').classList.add('hidden');
    el('cf-ing-search').focus();
  },

  _removeFormIng(ingId) {
    this._collectFormIngData();
    this._formIngredients = this._formIngredients.filter((f) => f.ingredient_id !== ingId);
    this._renderFormIngredients();
  },

  _wireFormIngSearch() {
    const input = el('cf-ing-search');
    const ac = el('cf-ing-ac');
    if (!input) return;

    const showAc = async (q) => {
      try {
        const params = { per_page: 20, sort: 'name' };
        if (q) params['filter[name]'] = q;
        const d = await get('/api/ingredients', params);
        const items = (d.data || []).filter(
          (i) => !this._formIngredients.some((f) => f.ingredient_id === i.id)
        );
        ac.innerHTML = '';
        if (!items.length) {
          ac.classList.add('hidden');
          return;
        }
        items.forEach((ing) => {
          const li = document.createElement('li');
          li.className = 'autocomplete-item';
          li.innerHTML = `<span>${escHtml(ing.name)}</span>`;
          li.addEventListener('mousedown', (e) => {
            e.preventDefault();
            this._addFormIng({ id: ing.id, name: ing.name });
          });
          ac.appendChild(li);
        });
        ac.classList.remove('hidden');
      } catch (e) {
        /* silent */
      }
    };

    input.addEventListener('focus', () => showAc(input.value.trim()));
    input.addEventListener(
      'input',
      debounce(() => showAc(input.value.trim()), 250)
    );
    input.addEventListener('blur', () => setTimeout(() => ac.classList.add('hidden'), 150));
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        ac.classList.add('hidden');
        input.blur();
      }
    });
  },

  async _submitForm(id) {
    const name = el('cf-name').value.trim();
    if (!name) {
      Toast.err('Name is required');
      return;
    }
    this._collectFormIngData();
    const glassVal = el('cf-glass').value;
    const methodVal = el('cf-method').value;
    const body = {
      name,
      glass_id: glassVal ? parseInt(glassVal) : null,
      method_id: methodVal ? parseInt(methodVal) : null,
      instructions: el('cf-instructions').value.trim(),
      garnish: el('cf-garnish').value.trim(),
      tags: el('cf-tags')
        .value.split(',')
        .map((t) => t.trim())
        .filter(Boolean),
      ingredients: this._formIngredients.map((ing, idx) => ({
        ingredient_id: ing.ingredient_id,
        amount: ing.amount !== '' ? parseFloat(ing.amount) || ing.amount : null,
        units: ing.units || null,
        note: ing.note || null,
        optional: ing.optional,
        sort: idx + 1,
      })),
    };
    try {
      if (id) {
        await put(`/api/cocktails/${id}`, body);
        Toast.show('Cocktail updated');
        this._cache.delete(id);
        this.open(id);
      } else {
        const d = await post('/api/cocktails', body);
        Toast.show('Cocktail created');
        this.load();
        if (d.data?.id) this.open(d.data.id);
      }
      Modal.close();
    } catch (e) {
      Toast.err(e.message);
    }
  },

  async deleteCurrent() {
    if (!this.currentId) return;
    if (!confirm(`Delete "${this.currentData?.name}"?`)) return;
    try {
      await del(`/api/cocktails/${this.currentId}`);
      Toast.show('Deleted');
      Nav.go('cocktails');
      this.load();
    } catch (e) {
      Toast.err(e.message);
    }
  },
};

// ── Favorites ──────────────────────────────────────────────────────────────

const Favorites = {
  shelfOnly: false,
  sortBy: 'name',
  sortDir: 'asc',
  _allItems: [],

  toggleShelf() {
    this.shelfOnly = !this.shelfOnly;
    el('fav-shelf-toggle').classList.toggle('shelf-active', this.shelfOnly);
    el('header-fav-shelf-toggle').classList.toggle('shelf-active', this.shelfOnly);
    this._render();
  },

  setSort(value) {
    const [field, dir] = value.split('-');
    this.sortBy = field;
    this.sortDir = dir;
    this._render();
  },

  async load() {
    const grid = el('favorites-list');
    grid.innerHTML = '<div class="loading-row"><div class="spinner"></div></div>';
    if (!isMobile()) calcLayout('favorites-list');
    try {
      const d = await get('/api/favorites');
      this._allItems = (d.data || []).map((c) => ({ ...c, is_favorited: true }));
      await this._render();
    } catch (e) {
      grid.innerHTML = '';
      el('favorites-empty').classList.remove('hidden');
      el('favorites-empty').querySelector('p').textContent = e.message;
    }
  },

  async _render() {
    const grid = el('favorites-list');
    const empty = el('favorites-empty');
    let items = [...this._allItems];

    if (this.shelfOnly && items.length) {
      try {
        const d = await get('/api/cocktails', { 'filter[on_shelf]': true, per_page: 500 });
        const shelfIds = new Set((d.data || []).map((c) => c.id));
        items = items.filter((c) => shelfIds.has(c.id));
      } catch (e) {
        /* fall back to unfiltered on error */
      }
    }

    if (!items.length) {
      grid.innerHTML = '';
      empty.querySelector('p').textContent = this.shelfOnly
        ? 'No favorites on your shelf.'
        : 'No favorites yet. Star a cocktail to save it here.';
      empty.classList.remove('hidden');
      return;
    }

    if (this.sortBy === 'name') {
      items.sort((a, b) =>
        this.sortDir === 'asc' ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name)
      );
    }

    empty.classList.add('hidden');
    grid.innerHTML = items.map((c) => Cocktails._card(c)).join('');

    await Cocktails._enrichCards(items);

    if (this.sortBy === 'rating') {
      const cards = [...grid.children];
      cards.sort((a, b) => {
        const rA = Cocktails._cache.get(parseInt(a.dataset.id))?.rating?.average ?? 0;
        const rB = Cocktails._cache.get(parseInt(b.dataset.id))?.rating?.average ?? 0;
        const rCmp = this.sortDir === 'desc' ? rB - rA : rA - rB;
        if (rCmp !== 0) return rCmp;
        return (a.querySelector('.card-name')?.textContent ?? '').localeCompare(
          b.querySelector('.card-name')?.textContent ?? ''
        );
      });
      grid.innerHTML = '';
      cards.forEach((c) => grid.appendChild(c));
    }
  },
};

// ── Ingredients ────────────────────────────────────────────────────────────

const Ingredients = {
  page: 1,
  lastMeta: null,
  query: '',
  sortBy: 'name',
  sortDir: 'asc',
  _cache: new Map(),
  _shelfState: new Map(),
  _cartState: new Map(),

  setSort(value) {
    const [field, dir] = value.split('-');
    this.sortBy = field;
    this.sortDir = dir;
    this.load(1);
  },

  async load(page = 1) {
    this.page = page;
    const grid = el('ingredient-list');
    const empty = el('ingredient-empty');
    grid.innerHTML = '<div class="loading-row"><div class="spinner"></div></div>';
    const params = { page, per_page: isMobile() ? 30 : calcLayout('ingredient-list') };
    if (this.query) params['filter[name]'] = this.query;
    params['sort'] =
      this.sortBy === 'name'
        ? this.sortDir === 'desc'
          ? '-name'
          : 'name'
        : this.sortDir === 'desc'
          ? `-${this.sortBy},name`
          : `${this.sortBy},name`;
    try {
      const d = await get('/api/ingredients', params);
      const items = d.data || [];
      this.lastMeta = d.meta;
      if (!items.length) {
        grid.innerHTML = '';
        empty.classList.remove('hidden');
        this._renderPagination();
        return;
      }
      empty.classList.add('hidden');
      items.forEach((i) => {
        this._shelfState.set(i.id, !!i.in_bar_shelf);
        this._cartState.set(i.id, !!i.in_shopping_list);
        if (i.in_bar_shelf) State.shelfIds.add(i.id);
      });
      grid.innerHTML = items.map((i) => this._card(i)).join('');
      this._renderPagination();
      this._enrichCards(items);
    } catch (e) {
      grid.innerHTML = '';
      empty.classList.remove('hidden');
      empty.querySelector('p').textContent = e.message;
    }
  },

  _card(i) {
    const onShelf = this._shelfState.get(i.id);
    const inCart = this._cartState.get(i.id);
    return `<div class="card row-layout" onclick="if(!event.target.closest('.ing-actions')) App.ingredients.showEdit(${i.id})">
      <div class="ing-thumb-wrap"><div class="card-thumb-slot" id="ithumb-${i.id}"></div></div>
      <div class="card-content">
        <div class="card-name">${escHtml(i.name)}</div>
        ${i.strength ? `<div class="card-sub">${i.strength}% ABV</div>` : ''}
        <div class="ing-actions">
          <button class="ing-action-btn ${onShelf ? 'shelf-active' : ''}" id="ishelf-${i.id}"
            onclick="App.ingredients.toggleShelf(${i.id})"
            title="${onShelf ? 'Remove from bar shelf' : 'Add to bar shelf'}">
            ${onShelf ? '✓ shelf' : '+ shelf'}
          </button>
          <button class="ing-action-btn ${inCart ? 'cart-active' : ''}" id="icart-${i.id}"
            onclick="App.ingredients.toggleCart(${i.id})"
            title="${inCart ? 'Remove from shopping list' : 'Add to shopping list'}">
            ${inCart ? '✓ list' : '+ list'}
          </button>
        </div>
      </div>
    </div>`;
  },

  async _enrichCards(items) {
    await Promise.all(
      items.map(async (i) => {
        try {
          const cached = this._cache.get(i.id);
          const data = cached ?? (await get(`/api/ingredients/${i.id}`)).data;
          if (!cached) this._cache.set(i.id, data);
          const slot = el(`ithumb-${i.id}`);
          if (!slot) return;
          if (data.images?.[0]) {
            const img = document.createElement('img');
            img.src = `/api/images/${data.images[0].id}/thumb`;
            img.className = 'card-thumb';
            img.loading = 'lazy';
            slot.replaceWith(img);
          } else {
            slot.className = 'card-thumb-empty';
          }
        } catch (e) {
          /* silent */
        }
      })
    );
  },

  async toggleShelf(id) {
    const onShelf = this._shelfState.get(id);
    try {
      if (onShelf) {
        await post('/api/shelf/batch-delete', { ingredients: [id] });
        State.shelfIds.delete(id);
        this._shelfState.set(id, false);
      } else {
        await post('/api/shelf/batch', { ingredients: [id] });
        State.shelfIds.add(id);
        this._shelfState.set(id, true);
      }
      const btn = el(`ishelf-${id}`);
      if (btn) {
        const now = !onShelf;
        btn.textContent = now ? '✓ shelf' : '+ shelf';
        btn.className = 'ing-action-btn' + (now ? ' shelf-active' : '');
        btn.title = now ? 'Remove from bar shelf' : 'Add to bar shelf';
      }
      Toast.show(onShelf ? 'Removed from shelf' : 'Added to shelf');
    } catch (e) {
      Toast.err(e.message);
    }
  },

  async toggleCart(id) {
    const inCart = this._cartState.get(id);
    try {
      if (inCart) {
        await post('/api/shopping-list/batch-delete', { ingredients: [{ id }] });
        this._cartState.set(id, false);
      } else {
        await post('/api/shopping-list/batch', { ingredients: [{ id, quantity: 1 }] });
        this._cartState.set(id, true);
      }
      const btn = el(`icart-${id}`);
      if (btn) {
        const now = !inCart;
        btn.textContent = now ? '✓ list' : '+ list';
        btn.className = 'ing-action-btn' + (now ? ' cart-active' : '');
        btn.title = now ? 'Remove from shopping list' : 'Add to shopping list';
      }
      Toast.show(inCart ? 'Removed from shopping list' : 'Added to shopping list');
    } catch (e) {
      Toast.err(e.message);
    }
  },

  _renderPagination() {
    const m = this.lastMeta;
    const bar = el('ingredient-pagination');
    if (!m || m.last_page <= 1) {
      bar.innerHTML = '';
      return;
    }
    const prev =
      m.current_page > 1
        ? `<button class="btn btn-ghost" onclick="App.ingredients.load(${m.current_page - 1})">‹ Prev</button>`
        : '<button class="btn btn-ghost" style="visibility:hidden">‹ Prev</button>';
    const next =
      m.current_page < m.last_page
        ? `<button class="btn btn-ghost" onclick="App.ingredients.load(${m.current_page + 1})">Next ›</button>`
        : '<button class="btn btn-ghost" style="visibility:hidden">Next ›</button>';
    bar.innerHTML = `${prev}<span>${m.current_page} / ${m.last_page}</span>${next}`;
  },

  showCreate() {
    this._showForm(null);
  },

  async showEdit(id) {
    const cached = this._cache.get(id);
    if (cached) {
      this._showForm(cached);
      return;
    }
    Modal.open('Loading…', '<div class="loading-row"><div class="spinner"></div></div>', '');
    try {
      const d = await get(`/api/ingredients/${id}`);
      this._cache.set(id, d.data);
      this._showForm(d.data);
    } catch (e) {
      Modal.close();
      Toast.err(e.message);
    }
  },

  _showForm(i) {
    const title = i ? `Edit: ${i.name}` : 'New Ingredient';
    const currentImg = i?.images?.[0];
    const imgSection = `
      <div class="form-group">
        <label class="form-label">Image</label>
        <input type="hidden" id="if-existing-img-ids"
               value="${escHtml(JSON.stringify((i?.images || []).map((im) => im.id)))}">
        ${
          currentImg
            ? `<div class="ing-form-img-wrap">
                <img id="if-img-preview" src="${escHtml(currentImg.thumb_url || `/api/images/${currentImg.id}/thumb`)}"
                     class="ing-form-img-preview" alt="${escHtml(i.name)}">
               </div>`
            : `<div class="ing-form-img-wrap"><div id="if-img-preview" class="ing-form-img-empty"></div></div>`
        }
        <div class="ing-form-img-inputs">
          <label class="ing-img-file-label">
            <input type="file" id="if-image-file" accept="image/*" onchange="App.ingredients._previewFile(this)">
            Choose file
          </label>
          <span class="ing-img-or">or</span>
          <input class="text-input ing-img-url" id="if-image-url" placeholder="Paste image URL…"
                 oninput="App.ingredients._previewUrl(this.value)">
        </div>
      </div>`;
    Modal.open(
      title,
      `<div class="form-group"><label class="form-label">Name *</label>
        <input class="text-input" id="if-name" value="${escHtml(i?.name || '')}" placeholder="Ingredient name"></div>
      <div class="form-group"><label class="form-label">Category</label>
        <input class="text-input" id="if-category" value="${escHtml(i?.category?.name || '')}" placeholder="e.g. Spirits"></div>
      <div class="form-group"><label class="form-label">Color (hex)</label>
        <input class="text-input" id="if-color" value="${escHtml(i?.color || '')}" placeholder="#ffffff"></div>
      <div class="form-group"><label class="form-label">Description</label>
        <textarea class="text-input" id="if-desc">${escHtml(i?.description || '')}</textarea></div>
      ${imgSection}`,
      `<button class="btn btn-ghost" onclick="App.modal.close()">Cancel</button>
       ${i ? `<button class="btn btn-danger" onclick="App.ingredients._delete(${i.id})">Delete</button>` : ''}
       <button class="btn btn-primary" onclick="App.ingredients._submit(${i?.id || 'null'})">${i ? 'Save' : 'Create'}</button>`
    );
    el('if-name').focus();
  },

  _previewFile(input) {
    const file = input.files?.[0];
    if (!file) return;
    el('if-image-url').value = '';
    const preview = el('if-img-preview');
    if (preview) {
      preview.src = URL.createObjectURL(file);
      preview.className = 'ing-form-img-preview';
    }
  },

  _previewUrl(url) {
    const fileInput = el('if-image-file');
    if (fileInput) fileInput.value = '';
    const preview = el('if-img-preview');
    if (!preview || !url.trim()) return;
    preview.src = url.trim();
    preview.className = 'ing-form-img-preview';
  },

  async _submit(id) {
    const name = el('if-name').value.trim();
    if (!name) {
      Toast.err('Name is required');
      return;
    }

    let imageId = null;
    const fileInput = el('if-image-file');
    const urlInput = el('if-image-url');

    if (fileInput?.files?.[0]) {
      const fd = new FormData();
      fd.append('images[0][image]', fileInput.files[0]);
      fd.append('images[0][sort]', '1');
      try {
        const r = await fetch('/api/images', { method: 'POST', body: fd });
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || d.message || 'Image upload failed');
        imageId = d.data?.[0]?.id;
      } catch (e) {
        Toast.err('Image upload failed: ' + e.message);
        return;
      }
    } else if (urlInput?.value?.trim()) {
      try {
        const d = await post('/api/images/from-url', { url: urlInput.value.trim() });
        imageId = d.data?.[0]?.id;
        if (!imageId) throw new Error('No image ID returned from BA');
      } catch (e) {
        Toast.err('Image URL failed: ' + e.message);
        return;
      }
    }

    // Delete old images so the new one replaces rather than appends.
    if (imageId) {
      const oldIds = JSON.parse(el('if-existing-img-ids')?.value || '[]');
      await Promise.allSettled(oldIds.map((oid) => del(`/api/images/${oid}`)));
    }

    const body = {
      name,
      description: el('if-desc').value.trim(),
      color: el('if-color').value.trim(),
    };
    if (imageId) body.images = [imageId];

    try {
      if (id) {
        await put(`/api/ingredients/${id}`, body);
        this._cache.delete(id);
        Toast.show('Ingredient updated');
      } else {
        await post('/api/ingredients', body);
        Toast.show('Ingredient created');
      }
      Modal.close();
      this.load(this.page);
      State.loadShelfIds();
    } catch (e) {
      Toast.err(e.message);
    }
  },

  async _delete(id) {
    if (!confirm('Delete this ingredient?')) return;
    try {
      await del(`/api/ingredients/${id}`);
      this._cache.delete(id);
      Toast.show('Deleted');
      Modal.close();
      this.load(this.page);
    } catch (e) {
      Toast.err(e.message);
    }
  },
};

// ── Tokens ─────────────────────────────────────────────────────────────────

const Tokens = {
  async load() {
    const grid = el('token-list');
    const empty = el('token-empty');
    grid.innerHTML = '<div class="loading-row"><div class="spinner"></div></div>';
    try {
      const d = await get('/api/tokens');
      const items = d.data || [];
      if (!items.length) {
        grid.innerHTML = '';
        empty.classList.remove('hidden');
        return;
      }
      empty.classList.add('hidden');
      grid.innerHTML = items
        .map(
          (t) => `
        <div class="card shelf-card">
          <div class="card-name">${escHtml(t.token_name || t.name)}</div>
          <div class="card-sub">Abilities: ${escHtml(t.abilities?.join(', ') || 'none')}</div>
          <div class="card-sub">Last used: ${t.last_used_at ? new Date(t.last_used_at).toLocaleDateString() : 'Never'}</div>
          <button class="remove-btn" onclick="App.tokens.delete(${t.id})" title="Revoke token">✕</button>
        </div>`
        )
        .join('');
    } catch (e) {
      grid.innerHTML = '';
      empty.classList.remove('hidden');
      empty.querySelector('p').textContent = e.message;
    }
  },

  showCreate() {
    Modal.open(
      'New API Token',
      `<div class="form-group">
        <label class="form-label">Token Name *</label>
        <input class="text-input" id="tf-name" placeholder="e.g. Mobile App">
      </div>
      <div class="form-group">
        <label class="form-label">Abilities (comma-separated)</label>
        <input class="text-input" id="tf-abilities" value="*" placeholder="e.g. *, cocktails.read">
        <p style="font-size:0.75rem;color:var(--text-dim);margin-top:4px">Use <strong>*</strong> for full access.</p>
      </div>`,
      `<button class="btn btn-ghost" onclick="App.modal.close()">Cancel</button>
       <button class="btn btn-primary" onclick="App.tokens.submit()">Create Token</button>`
    );
    el('tf-name').focus();
  },

  async submit() {
    const name = el('tf-name').value.trim();
    const abilities = el('tf-abilities')
      .value.split(',')
      .map((s) => s.trim())
      .filter(Boolean);
    if (!name) {
      Toast.err('Name is required');
      return;
    }
    try {
      const d = await post('/api/tokens', { name, abilities });
      const plainToken = d.data?.token;
      Modal.open(
        'Token Created',
        `<p style="font-size:0.9rem;margin-bottom:12px">Copy this token now. It will not be shown again!</p>
         <div class="card" style="background:var(--bg-deep);cursor:text;user-select:all;word-break:break-all;font-family:monospace;font-size:0.85rem;padding:12px;border:1px solid var(--accent)">
           ${escHtml(plainToken)}
         </div>`,
        `<button class="btn btn-primary" onclick="App.modal.close(); App.tokens.load()">I have copied it</button>`
      );
    } catch (e) {
      Toast.err(e.message);
    }
  },

  async delete(id) {
    if (!confirm('Are you sure you want to revoke this token?')) return;
    try {
      await del(`/api/tokens/${id}`);
      Toast.show('Token revoked');
      this.load();
    } catch (e) {
      Toast.err(e.message);
    }
  },
};

// ── Auth ───────────────────────────────────────────────────────────────────

const Auth = {
  async login() {
    const email = el('login-email').value.trim();
    const password = el('login-pass').value.trim();
    const msg = el('login-msg');
    if (!email || !password) {
      msg.textContent = 'Enter email and password';
      return;
    }
    msg.textContent = 'Logging in…';
    try {
      const d = await post('/api/auth/login', { email, password });
      Toast.show(`Welcome, ${d.user?.name || 'User'}`);
      el('logout-btn').classList.remove('hidden');
      App.init(); // Refresh config and go to shelf
    } catch (e) {
      msg.textContent = e.message;
    }
  },

  async logout() {
    try {
      await post('/api/auth/logout');
      el('logout-btn').classList.add('hidden');
      App.nav.go('login');
    } catch (e) {
      Toast.err(e.message);
    }
  },
};

// ── Users ──────────────────────────────────────────────────────────────────

const Users = {
  async load() {
    const grid = el('user-list');
    const empty = el('user-empty');
    grid.innerHTML = '<div class="loading-row"><div class="spinner"></div></div>';
    try {
      const d = await get('/api/users');
      const items = d.data || [];
      if (!items.length) {
        grid.innerHTML = '';
        empty.classList.remove('hidden');
        return;
      }
      empty.classList.add('hidden');
      grid.innerHTML = items
        .map(
          (u) => `
        <div class="card shelf-card">
          <div class="card-name">${escHtml(u.name)}</div>
          <div class="card-sub">${escHtml(u.email)}</div>
          <div class="card-sub">Role: ${u.is_admin ? 'Admin' : 'User'}</div>
          <button class="remove-btn" onclick="App.users.delete(${u.id})" title="Delete user">✕</button>
        </div>`
        )
        .join('');
    } catch (e) {
      grid.innerHTML = '';
      empty.classList.remove('hidden');
      empty.querySelector('p').textContent = e.message;
    }
  },

  showCreate() {
    Modal.open(
      'New User',
      `<div class="form-group">
        <label class="form-label">Name *</label>
        <input class="text-input" id="uf-name">
      </div>
      <div class="form-group">
        <label class="form-label">Email *</label>
        <input type="email" class="text-input" id="uf-email">
      </div>
      <div class="form-group">
        <label class="form-label">Password *</label>
        <input type="password" class="text-input" id="uf-pass">
      </div>`,
      `<button class="btn btn-ghost" onclick="App.modal.close()">Cancel</button>
       <button class="btn btn-primary" onclick="App.users.submit()">Create User</button>`
    );
  },

  async submit() {
    const name = el('uf-name').value;
    const email = el('uf-email').value;
    const password = el('uf-pass').value;
    if (!name || !email || !password) {
      Toast.err('All fields are required');
      return;
    }
    try {
      await post('/api/users', { name, email, password });
      Toast.show('User created');
      Modal.close();
      this.load();
    } catch (e) {
      Toast.err(e.message);
    }
  },

  async delete(id) {
    if (!confirm('Are you sure you want to delete this user?')) return;
    try {
      await del(`/api/users/${id}`);
      Toast.show('User deleted');
      this.load();
    } catch (e) {
      Toast.err(e.message);
    }
  },
};

// ── Shopping List ──────────────────────────────────────────────────────────

const ShoppingList = {
  async load() {
    const grid = el('shopping-list-items');
    const empty = el('shopping-list-empty');
    grid.innerHTML = '<div class="loading-row"><div class="spinner"></div></div>';
    try {
      const d = await get('/api/shopping-list');
      const items = d.data || [];
      if (!items.length) {
        grid.innerHTML = '';
        empty.classList.remove('hidden');
        return;
      }
      empty.classList.add('hidden');
      grid.innerHTML = items
        .map((item) => {
          const ing = item.ingredient;
          const onShelf = State.shelfIds.has(ing.id);
          return `<div class="card row-layout shelf-card">
          <div class="card-content">
            <div class="card-name">${escHtml(ing.name)}</div>
            ${item.quantity ? `<div class="card-sub">Qty: ${item.quantity}</div>` : ''}
          </div>
          ${
            !onShelf
              ? `<button class="ing-action-btn" style="flex-shrink:0"
            onclick="App.shoppingList.addToShelf(${ing.id}, '${escHtml(ing.name)}')"
            title="Add to bar shelf">+ shelf</button>`
              : ''
          }
          <button class="remove-btn" style="position:static;margin-left:${onShelf ? 'auto' : '6px'}"
            onclick="App.shoppingList.remove(${ing.id})" title="Remove from list">✕</button>
        </div>`;
        })
        .join('');
    } catch (e) {
      grid.innerHTML = '';
      empty.classList.remove('hidden');
      empty.querySelector('p').textContent = e.message;
    }
  },

  async remove(id) {
    try {
      await post('/api/shopping-list/batch-delete', { ingredients: [{ id }] });
      const btn = el(`icart-${id}`);
      if (btn) {
        btn.textContent = '+ list';
        btn.className = 'ing-action-btn';
        btn.title = 'Add to shopping list';
        Ingredients._cartState.set(id, false);
      }
      Toast.show('Removed from list');
      this.load();
    } catch (e) {
      Toast.err(e.message);
    }
  },

  async addToShelf(id, name) {
    try {
      await post('/api/shelf/batch', { ingredients: [id] });
      State.shelfIds.add(id);
      const shelfBtn = el(`ishelf-${id}`);
      if (shelfBtn) {
        shelfBtn.textContent = '✓ shelf';
        shelfBtn.className = 'ing-action-btn shelf-active';
        Ingredients._shelfState.set(id, true);
      }
      Toast.show(`${name} added to shelf`);
      this.load();
    } catch (e) {
      Toast.err(e.message);
    }
  },

  async clearAll() {
    if (!confirm('Remove all items from your shopping list?')) return;
    try {
      const d = await get('/api/shopping-list');
      const ids = (d.data || []).map((i) => ({ id: i.ingredient.id }));
      if (!ids.length) return;
      await post('/api/shopping-list/batch-delete', { ingredients: ids });
      // Reset any visible ingredient card buttons
      ids.forEach(({ id }) => {
        const btn = el(`icart-${id}`);
        if (btn) {
          btn.textContent = '+ list';
          btn.className = 'ing-action-btn';
        }
        Ingredients._cartState.set(id, false);
      });
      Toast.show('Shopping list cleared');
      this.load();
    } catch (e) {
      Toast.err(e.message);
    }
  },
};

// ── Bar Statistics ─────────────────────────────────────────────────────────

const Stats = {
  _NUMS: [
    { key: 'total_cocktails', label: 'Cocktails', icon: 'local_bar' },
    { key: 'total_ingredients', label: 'Ingredients', icon: 'eco' },
    { key: 'total_shelf_ingredients', label: 'My shelf', icon: 'inventory_2' },
    { key: 'total_bar_shelf_ingredients', label: 'Bar shelf', icon: 'liquor' },
    { key: 'total_favorited_cocktails', label: 'Favorites', icon: 'star' },
    { key: 'total_shelf_cocktails', label: 'I can make', icon: 'check_circle' },
    { key: 'total_bar_shelf_cocktails', label: 'Bar can make', icon: 'sports_bar' },
    { key: 'total_collections', label: 'Collections', icon: 'collections_bookmark' },
    { key: 'total_bar_members', label: 'Members', icon: 'group' },
  ],

  _LISTS: [
    {
      key: 'most_popular_ingredients',
      title: 'Most Popular Ingredients',
      icon: 'emoji_events',
      row: (i) => ({ name: i.name, badge: `${i.cocktails_count} cocktails` }),
    },
    {
      key: 'top_rated_cocktails',
      title: 'Top Rated Cocktails',
      icon: 'star',
      row: (i) => ({ name: i.name, badge: '★'.repeat(Math.round(i.avg_rating)) }),
    },
    {
      key: 'your_top_ingredients',
      title: 'Your Top Ingredients',
      icon: 'inventory_2',
      row: (i) => ({ name: i.name, badge: `${i.cocktails_count} cocktails` }),
    },
    {
      key: 'favorite_tags',
      title: 'Favorite Tags',
      icon: 'label',
      row: (i) => ({ name: i.name, badge: `${i.cocktails_count} cocktails` }),
    },
  ],

  async load() {
    const body = el('stats-body');
    body.innerHTML = '<div class="loading-row"><div class="spinner"></div></div>';
    try {
      const cfg = await get('/config');
      if (!cfg.bar_id) {
        body.innerHTML =
          '<p class="empty-state">No bar selected. Go to Settings to set an active bar.</p>';
        return;
      }
      const d = await get(`/api/bars/${cfg.bar_id}/stats`);
      const s = d.data || {};

      const numsHtml = this._NUMS
        .filter((n) => n.key in s)
        .map(
          (n) => `
          <div class="stat-num-card">
            <span class="stat-num-icon material-symbols-rounded">${n.icon}</span>
            <div class="stat-num-value">${s[n.key] ?? '—'}</div>
            <div class="stat-num-label">${n.label}</div>
          </div>`
        )
        .join('');

      const listsHtml = this._LISTS
        .filter((l) => s[l.key]?.length)
        .map((l) => {
          const rows = s[l.key]
            .map((item, idx) => {
              const { name, badge } = l.row(item);
              return `<div class="stat-list-row">
              <span class="stat-list-rank">${idx + 1}</span>
              <span class="stat-list-name">${escHtml(name)}</span>
              <span class="stat-list-badge">${escHtml(badge)}</span>
            </div>`;
            })
            .join('');
          return `<div class="stat-list-card">
            <div class="stat-list-header">
              <span class="material-symbols-rounded">${l.icon}</span>
              ${l.title}
            </div>
            ${rows}
          </div>`;
        })
        .join('');

      body.innerHTML = `
        <div class="stat-nums">${numsHtml}</div>
        <div class="stat-lists">${listsHtml}</div>`;
    } catch (e) {
      body.innerHTML = `<p style="color:#f87171;padding:24px">${escHtml(e.message)}</p>`;
    }
  },
};

// ── Glasses ────────────────────────────────────────────────────────────────

const Glasses = {
  _cache: null,

  async load() {
    const grid = el('glass-list');
    const empty = el('glass-empty');
    grid.innerHTML = '<div class="loading-row"><div class="spinner"></div></div>';
    try {
      const d = await get('/api/glasses');
      this._cache = d.data || [];
      Cocktails._glasses = this._cache;
      if (!this._cache.length) {
        grid.innerHTML = '';
        empty.classList.remove('hidden');
        return;
      }
      empty.classList.add('hidden');
      grid.innerHTML = this._cache
        .map(
          (g) => `
        <div class="card shelf-card">
          <div class="card-name">${escHtml(g.name)}</div>
          ${g.volume ? `<div class="card-sub">${g.volume} ${g.volume_units || 'ml'}</div>` : ''}
          <div class="card-actions">
            <button class="btn btn-ghost btn-sm" onclick="App.glasses._showForm(${g.id})">Edit</button>
            <button class="btn btn-ghost btn-sm" style="color:var(--accent)" onclick="App.glasses.delete(${g.id})">Delete</button>
          </div>
        </div>`
        )
        .join('');
    } catch (e) {
      grid.innerHTML = '';
      empty.classList.remove('hidden');
      empty.querySelector('p').textContent = e.message;
    }
  },

  showCreate() {
    this._showForm(null);
  },

  _showForm(id) {
    const g = id != null ? this._cache?.find((x) => x.id === id) : null;
    Modal.open(
      g ? `Edit: ${g.name}` : 'New Glass',
      `<div class="form-group"><label class="form-label">Name *</label>
         <input class="text-input" id="gf-name" value="${escHtml(g?.name || '')}" placeholder="e.g. Rocks glass"></div>
       <div class="form-group"><label class="form-label">Volume (ml, optional)</label>
         <input class="text-input" id="gf-volume" type="number" value="${g?.volume ?? ''}" placeholder="e.g. 300"></div>`,
      `${g ? `<button class="btn btn-ghost" style="color:var(--accent);margin-right:auto" onclick="App.glasses.delete(${g.id})">Delete</button>` : ''}
       <button class="btn btn-ghost" onclick="App.modal.close()">Cancel</button>
       <button class="btn btn-primary" onclick="App.glasses._submit(${g?.id ?? 'null'})">${g ? 'Save' : 'Create'}</button>`
    );
    el('gf-name').focus();
  },

  async _submit(id) {
    const name = el('gf-name').value.trim();
    if (!name) {
      Toast.err('Name is required');
      return;
    }
    const vol = el('gf-volume').value;
    const body = { name, volume: vol ? parseFloat(vol) : null };
    try {
      if (id) {
        await put(`/api/glasses/${id}`, body);
        Toast.show('Glass updated');
      } else {
        await post('/api/glasses', body);
        Toast.show('Glass created');
      }
      this._cache = null;
      Cocktails._glasses = null;
      Modal.close();
      this.load();
    } catch (e) {
      Toast.err(e.message);
    }
  },

  async delete(id) {
    const name = this._cache?.find((g) => g.id === id)?.name || 'this glass';
    if (!confirm(`Delete "${name}"?`)) return;
    try {
      await del(`/api/glasses/${id}`);
      Toast.show('Deleted');
      this._cache = null;
      Cocktails._glasses = null;
      Modal.close();
      this.load();
    } catch (e) {
      Toast.err(e.message);
    }
  },
};

// ── Methods ────────────────────────────────────────────────────────────────

const Methods = {
  _cache: null,

  async load() {
    const grid = el('method-list');
    const empty = el('method-empty');
    grid.innerHTML = '<div class="loading-row"><div class="spinner"></div></div>';
    try {
      const d = await get('/api/methods');
      this._cache = d.data || [];
      Cocktails._methods = this._cache;
      if (!this._cache.length) {
        grid.innerHTML = '';
        empty.classList.remove('hidden');
        return;
      }
      empty.classList.add('hidden');
      grid.innerHTML = this._cache
        .map(
          (m) => `
        <div class="card shelf-card">
          <div class="card-name">${escHtml(m.name)}</div>
          <div class="card-sub">Dilution: ${m.dilution_percentage}%</div>
          <div class="card-actions">
            <button class="btn btn-ghost btn-sm" onclick="App.methods._showForm(${m.id})">Edit</button>
            <button class="btn btn-ghost btn-sm" style="color:var(--accent)" onclick="App.methods.delete(${m.id})">Delete</button>
          </div>
        </div>`
        )
        .join('');
    } catch (e) {
      grid.innerHTML = '';
      empty.classList.remove('hidden');
      empty.querySelector('p').textContent = e.message;
    }
  },

  showCreate() {
    this._showForm(null);
  },

  _showForm(id) {
    const m = id != null ? this._cache?.find((x) => x.id === id) : null;
    Modal.open(
      m ? `Edit: ${m.name}` : 'New Method',
      `<div class="form-group"><label class="form-label">Name *</label>
         <input class="text-input" id="mf-name" value="${escHtml(m?.name || '')}" placeholder="e.g. Shaken"></div>
       <div class="form-group"><label class="form-label">Dilution %</label>
         <input class="text-input" id="mf-dilution" type="number" value="${m?.dilution_percentage ?? 0}" placeholder="0"></div>`,
      `${m ? `<button class="btn btn-ghost" style="color:var(--accent);margin-right:auto" onclick="App.methods.delete(${m.id})">Delete</button>` : ''}
       <button class="btn btn-ghost" onclick="App.modal.close()">Cancel</button>
       <button class="btn btn-primary" onclick="App.methods._submit(${m?.id ?? 'null'})">${m ? 'Save' : 'Create'}</button>`
    );
    el('mf-name').focus();
  },

  async _submit(id) {
    const name = el('mf-name').value.trim();
    if (!name) {
      Toast.err('Name is required');
      return;
    }
    const body = { name, dilution_percentage: parseInt(el('mf-dilution').value) || 0 };
    try {
      if (id) {
        await put(`/api/methods/${id}`, body);
        Toast.show('Method updated');
      } else {
        await post('/api/methods', body);
        Toast.show('Method created');
      }
      this._cache = null;
      Cocktails._methods = null;
      Modal.close();
      this.load();
    } catch (e) {
      Toast.err(e.message);
    }
  },

  async delete(id) {
    const name = this._cache?.find((m) => m.id === id)?.name || 'this method';
    if (!confirm(`Delete "${name}"?`)) return;
    try {
      await del(`/api/methods/${id}`);
      Toast.show('Deleted');
      this._cache = null;
      Cocktails._methods = null;
      Modal.close();
      this.load();
    } catch (e) {
      Toast.err(e.message);
    }
  },
};

// ── App bootstrap ──────────────────────────────────────────────────────────

const App = {
  nav: Nav,
  modal: Modal,
  auth: Auth,
  shelf: Shelf,
  cocktails: Cocktails,
  favorites: Favorites,
  ingredients: Ingredients,
  shoppingList: ShoppingList,
  tokens: Tokens,
  users: Users,
  glasses: Glasses,
  methods: Methods,
  settings: Settings,
  stats: Stats,

  async init() {
    try {
      const cfg = await get('/config');
      if (!cfg.api_url) {
        this.nav.go('settings');
        return;
      }
      if (!cfg.is_logged_in) {
        el('logout-btn').classList.add('hidden');
        this.nav.go('login');
        return;
      }

      el('logout-btn').classList.remove('hidden');
      this.loadVersion();

      // Wire search inputs
      el('shelf-search').addEventListener(
        'input',
        debounce((e) => Shelf.filter(e.target.value), 250)
      );
      el('cocktail-search').addEventListener(
        'input',
        debounce((e) => {
          Cocktails.query = e.target.value;
          Cocktails.load(1);
        }, 350)
      );
      el('ingredient-search').addEventListener(
        'input',
        debounce((e) => {
          Ingredients.query = e.target.value;
          Ingredients.load(1);
        }, 350)
      );

      // Wire ingredient filter autocomplete
      const ingFilterInput = el('ing-filter-input');
      const ingAutoList = el('ing-autocomplete');

      el('ing-token-box').addEventListener('click', () => ingFilterInput.focus());

      const showIngAc = async (q) => {
        try {
          const params = { per_page: 20, sort: 'name' };
          if (q) params['filter[name]'] = q;
          const d = await get('/api/ingredients', params);
          const items = (d.data || []).filter(
            (i) => !Cocktails.ingredientFilter.some((f) => f.id === i.id)
          );
          Cocktails._acHighlight = -1;
          ingAutoList.innerHTML = '';
          if (!items.length) {
            ingAutoList.classList.add('hidden');
            return;
          }
          items.forEach((ing) => {
            const li = document.createElement('li');
            li.className = 'autocomplete-item';
            li.innerHTML = `<div class="ac-ing-img" id="ac-img-${ing.id}"><span class="ac-ing-placeholder">🍶</span></div><span>${escHtml(ing.name)}</span>`;
            li.addEventListener('mousedown', (e) => {
              e.preventDefault();
              Cocktails._selectIngredient({ id: ing.id, name: ing.name });
            });
            ingAutoList.appendChild(li);
          });
          ingAutoList.classList.remove('hidden');

          // Enrich each row with an image, using the ingredient detail cache when warm
          items.forEach(async (ing) => {
            try {
              const cached = Ingredients._cache.get(ing.id);
              const data = cached ?? (await get(`/api/ingredients/${ing.id}`)).data;
              if (!cached) Ingredients._cache.set(ing.id, data);
              if (data.images?.[0]) {
                const slot = el(`ac-img-${ing.id}`);
                if (slot) {
                  const img = document.createElement('img');
                  img.src = `/api/images/${data.images[0].id}/thumb`;
                  img.alt = '';
                  slot.innerHTML = '';
                  slot.appendChild(img);
                }
              }
            } catch (e) {
              /* silent */
            }
          });
        } catch (e) {
          /* silent */
        }
      };

      ingFilterInput.addEventListener('focus', () => showIngAc(ingFilterInput.value.trim()));

      ingFilterInput.addEventListener(
        'input',
        debounce(() => {
          const q = ingFilterInput.value.trim();
          showIngAc(q);
        }, 250)
      );

      ingFilterInput.addEventListener('keydown', (e) => {
        const items = ingAutoList.querySelectorAll('.autocomplete-item');
        if (!items.length) return;
        if (e.key === 'ArrowDown') {
          e.preventDefault();
          Cocktails._acHighlight = Math.min(Cocktails._acHighlight + 1, items.length - 1);
          items.forEach((it, i) => it.classList.toggle('ac-active', i === Cocktails._acHighlight));
        } else if (e.key === 'ArrowUp') {
          e.preventDefault();
          Cocktails._acHighlight = Math.max(Cocktails._acHighlight - 1, -1);
          items.forEach((it, i) => it.classList.toggle('ac-active', i === Cocktails._acHighlight));
        } else if (e.key === 'Enter' && Cocktails._acHighlight >= 0) {
          e.preventDefault();
          items[Cocktails._acHighlight]?.dispatchEvent(new MouseEvent('mousedown'));
        } else if (e.key === 'Escape') {
          ingAutoList.classList.add('hidden');
          ingFilterInput.blur();
        }
      });

      ingFilterInput.addEventListener('blur', () => {
        setTimeout(() => ingAutoList.classList.add('hidden'), 150);
      });

      window.addEventListener(
        'resize',
        debounce(() => {
          if (isMobile()) return;
          const view = Nav.current;
          if (view === 'cocktails') Cocktails.load(Cocktails.page);
          else if (view === 'ingredients') Ingredients.load(Ingredients.page);
          else if (view === 'favorites') Favorites.load();
        }, 400)
      );

      el('cocktail-list').addEventListener('scroll', () => {
        if (!isMobile()) return;
        const g = el('cocktail-list');
        if (g.scrollHeight - g.scrollTop - g.clientHeight < 300) Cocktails._maybeLoadMore();
      });

      // Initialise unit toggle label from saved preference
      el('unit-toggle-btn').textContent = UnitPref.get();

      // Load initial view
      await Cocktails.load();
      this.nav.go('cocktails');
      el('app-header').classList.add('cocktails-active');

      // Lazy-load other views on tab activation
      const syncHeaderClasses = (view) => {
        el('app-header').classList.toggle('cocktails-active', view === 'cocktails');
        el('app-header').classList.toggle('favorites-active', view === 'favorites');
      };

      const origGo = Nav.go.bind(Nav);
      Nav.go = async (view) => {
        origGo(view);
        syncHeaderClasses(view);
        if (view === 'settings') Settings.load();
        if (view === 'shelf' && !Shelf.items.length) Shelf.load();
        if (view === 'favorites') Favorites.load();
        if (view === 'ingredients' && !Ingredients.lastMeta) Ingredients.load();
        if (view === 'shopping-list') ShoppingList.load();
        if (view === 'tokens') Tokens.load();
        if (view === 'users') Users.load();
      };

      const origBack = Nav.back.bind(Nav);
      Nav.back = () => {
        origBack();
        syncHeaderClasses(Nav.current);
      };
    } catch (e) {
      if (e.message !== 'Please login') console.error('Init error:', e);
    }
  },

  async _loadBars(selectedId) {
    try {
      const d = await get('/api/bars');
      const bars = d.data || [];
      const sel = el('cfg-bar');
      sel.innerHTML = bars
        .map(
          (b) =>
            `<option value="${b.id}" ${b.id == selectedId ? 'selected' : ''}>${escHtml(b.name)}</option>`
        )
        .join('');
      if (!selectedId && bars.length) {
        el('cfg-bar').value = bars[0].id;
        this.saveBar();
      }
    } catch (e) {
      /* silent */
    }
  },

  async loadVersion() {
    try {
      const d = await get('/api/server/version');
      el('server-version').textContent = `API Version: ${d.data?.version || 'Unknown'}`;
    } catch (e) {
      el('server-version').textContent = 'API Version: Error';
    }
  },
};

document.addEventListener('DOMContentLoaded', () => App.init());
