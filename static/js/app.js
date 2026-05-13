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
    if (Array.isArray(v)) v.forEach(item => qs.append(k, item));
    else qs.append(k, v);
  }
  return api('GET', `${path}?${qs}`);
}
function post(path, body) { return api('POST', path, body); }
function put(path, body)  { return api('PUT',  path, body); }
function del(path)        { return api('DELETE', path); }

function el(id) { return document.getElementById(id); }
function qs(sel, ctx) { return (ctx || document).querySelector(sel); }

function debounce(fn, ms) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

function escHtml(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ── Layout helpers ─────────────────────────────────────────────────────────

const DESKTOP_PX    = 900;               // mobile/desktop breakpoint
const CHROME_H      = 44 + 72 + 48;     // header + nav + toolbar (px)
const CARD_MIN_W    = 300;
const CARD_MIN_H    = 160;
const CARD_GAP      = 8;
const CARD_PAD      = 8;

function isMobile() { return window.innerWidth < DESKTOP_PX; }

function calcLayout(gridId) {
  const grid = el(gridId);
  const cols = Math.max(1, Math.floor((window.innerWidth  - CARD_PAD * 2 + CARD_GAP) / (CARD_MIN_W + CARD_GAP)));
  const rows = Math.max(1, Math.floor((window.innerHeight - CHROME_H - CARD_PAD * 2 + CARD_GAP) / (CARD_MIN_H + CARD_GAP)));
  grid.style.gridTemplateColumns = `repeat(${cols}, 1fr)`;
  grid.style.gridTemplateRows    = `repeat(${rows}, 1fr)`;
  return cols * rows;
}

function isOnShelf(ingId, ingredient) {
  return State.shelfIds.has(ingId)
      || !!ingredient?.in_bar_shelf
      || !!Ingredients._shelfState.get(ingId);
}

// ── Unit preference ────────────────────────────────────────────────────────

const UnitPref = {
  get() { return localStorage.getItem('sugar-rim-units') || 'oz'; },
  set(u) { localStorage.setItem('sugar-rim-units', u); },

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
  }
};

// ── Toast ──────────────────────────────────────────────────────────────────

const Toast = {
  _t: null,
  show(msg, isErr = false) {
    const t = el('toast');
    t.textContent = msg;
    t.className = 'toast' + (isErr ? ' err' : '');
    clearTimeout(this._t);
    this._t = setTimeout(() => { t.classList.add('hidden'); }, 2800);
  },
  err(msg) { this.show(msg, true); }
};

// ── Modal ──────────────────────────────────────────────────────────────────

const Modal = {
  open(title, bodyHtml, footerHtml) {
    el('modal-title').textContent = title;
    el('modal-body').innerHTML = bodyHtml;
    el('modal-footer').innerHTML = footerHtml || '';
    el('modal-overlay').classList.remove('hidden');
  },
  close() { el('modal-overlay').classList.add('hidden'); },
  closeOnBackdrop(e) { if (e.target === el('modal-overlay')) this.close(); },
  body() { return el('modal-body'); },
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
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    const section = el(`view-${view}`);
    if (section) section.classList.add('active');
    const btn = qs(`[data-view="${view}"]`);
    if (btn) btn.classList.add('active');
  }
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
    } catch (e) { /* silent */ }
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
    if (!url) { msg.textContent = '✗ URL is required'; msg.className = 'cfg-status err'; return; }
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
      if (!bars.length) { sel.innerHTML = '<option value="">No bars found</option>'; return; }
      sel.innerHTML = bars.map(b =>
        `<option value="${b.id}" ${String(b.id) === String(currentBarId) ? 'selected' : ''}>${escHtml(b.name)}</option>`
      ).join('');
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
    if (!bar_id) { Toast.err('Select a bar first'); return; }
    try {
      await post('/config', { bar_id });
      msg.textContent = '✓ Bar saved';
      msg.className = 'cfg-status ok';
      Toast.show('Active bar updated');
    } catch (e) {
      msg.textContent = '✗ ' + e.message;
      msg.className = 'cfg-status err';
    }
  }
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
    } catch (e) { /* silent */ }
  },

  async loadShelfIds() {
    try {
      const d = await get('/api/shelf');
      this.shelfIds = new Set((d.data || []).map(i => i.id));
    } catch (e) {
      this.shelfIds = new Set();
    }
  }
};

// ── Shelf ──────────────────────────────────────────────────────────────────

const Shelf = {
  items: [],
  filtered: [],

  async load() {
    const grid  = el('shelf-list');
    const empty = el('shelf-empty');
    grid.innerHTML = '<div class="loading-row"><div class="spinner"></div></div>';
    try {
      const d = await get('/api/shelf');
      this.items = d.data || [];
      State.shelfIds = new Set(this.items.map(i => i.id));
      this.render(this.items);
    } catch (e) {
      grid.innerHTML = '';
      empty.classList.remove('hidden');
      empty.querySelector('p').textContent = e.message;
    }
  },

  render(items) {
    const grid  = el('shelf-list');
    const empty = el('shelf-empty');
    if (!items.length) { grid.innerHTML = ''; empty.classList.remove('hidden'); return; }
    empty.classList.add('hidden');
    grid.innerHTML = items.map(i => {
      const thumb = i.images?.[0] ? `<img src="/api/images/${i.images[0].id}/thumb" class="card-thumb">` : '';
      return `<div class="card shelf-card row-layout">
        ${thumb}
        <div class="card-content">
          <div class="card-name">${escHtml(i.name)}</div>
        </div>
        <button class="remove-btn" style="position:static;margin-left:auto;" onclick="App.shelf.remove(${i.id})" title="Remove from shelf">✕</button>
      </div>`;
    }).join('');
  },

  filter(q) {
    const lq = q.toLowerCase();
    this.render(q ? this.items.filter(i => (i.name || i.ingredient?.name || '').toLowerCase().includes(lq)) : this.items);
  },

  async remove(id) {
    try {
      await post('/api/shelf/batch-delete', { ingredients: [id] });
      State.shelfIds.delete(id);
      this.items = this.items.filter(i => i.id !== id);
      this.render(this.items);
      Toast.show('Removed from shelf');
    } catch (e) { Toast.err(e.message); }
  },

  showAddModal() {
    Modal.open('Add to Shelf',
      `<div class="form-group">
        <label class="form-label">Search ingredient</label>
        <input class="text-input" id="shelf-add-search" placeholder="Type to search…">
        <div id="shelf-add-results" style="margin-top:8px;display:flex;flex-direction:column;gap:6px;max-height:260px;overflow-y:auto"></div>
      </div>`,
      `<button class="btn btn-ghost" onclick="App.modal.close()">Cancel</button>`
    );
    const inp = el('shelf-add-search');
    inp.addEventListener('input', debounce(() => this._searchForAdd(inp.value), 300));
    inp.focus();
  },

  async _searchForAdd(q) {
    if (q.length < 2) return;
    const res = el('shelf-add-results');
    res.innerHTML = '<div class="spinner"></div>';
    try {
      const d = await get('/api/ingredients', { 'filter[name]': q, per_page: 20 });
      const items = d.data || [];
      if (!items.length) { res.innerHTML = '<span style="color:var(--text-dim);font-size:.85rem">No results</span>'; return; }
      res.innerHTML = items.map(i => {
        const onShelf = State.shelfIds.has(i.id);
        return `<button class="card" style="min-height:auto;padding:8px 12px;flex-direction:row;align-items:center;gap:8px;cursor:${onShelf?'default':'pointer'};opacity:${onShelf?'.5':'1'}"
          ${onShelf ? 'disabled' : `onclick="App.shelf.addById(${i.id}, '${escHtml(i.name)}')"`}>
          <span style="flex:1;font-size:.88rem">${escHtml(i.name)}</span>
          ${onShelf ? '<span style="color:var(--accent2);font-size:.75rem">on shelf</span>' : ''}
        </button>`;
      }).join('');
    } catch (e) { res.innerHTML = `<span style="color:#f87171;font-size:.85rem">${escHtml(e.message)}</span>`; }
  },

  async addById(id, name) {
    try {
      await post('/api/shelf/batch', { ingredients: [id] });
      State.shelfIds.add(id);
      Toast.show(`Added ${name} to shelf`);
      Modal.close();
      this.load();
    } catch (e) { Toast.err(e.message); }
  }
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
  _acHighlight: -1,
  currentId: null,
  currentData: null,
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
    if (this.ingredientFilter.some(f => f.id === ing.id)) return;
    this.ingredientFilter.push(ing);
    this._renderChips();
    this.load(1);
  },

  removeIngredient(id) {
    this.ingredientFilter = this.ingredientFilter.filter(f => f.id !== id);
    this._renderChips();
    this.load(1);
  },

  _renderChips() {
    el('ing-chips').innerHTML = this.ingredientFilter.map(ing =>
      `<span class="ing-chip">${escHtml(ing.name)}<button class="ing-chip-remove" onclick="Cocktails.removeIngredient(${ing.id})" title="Remove">×</button></span>`
    ).join('');
  },

  _selectIngredient(ing) {
    el('ing-filter-input').value = '';
    el('ing-autocomplete').classList.add('hidden');
    this._acHighlight = -1;
    this.addIngredient(ing);
  },

  _buildParams(page, perPage) {
    const params = { page, per_page: perPage };
    if (this.query) params['filter[name]'] = this.query;
    if (this.shelfOnly) params['filter[on_shelf]'] = true;
    if (this.ingredientFilter.length) {
      params['filter[ingredient_name][]'] = this.ingredientFilter.map(i => i.name);
    }
    if (this.sortBy === 'rating') {
      params['sort'] = this.sortDir === 'desc' ? '-average_rating,name' : 'average_rating,name';
    } else {
      params['sort'] = this.sortDir === 'desc' ? '-name' : 'name';
    }
    return params;
  },

  async load(page = 1) {
    this.page = page;
    const grid  = el('cocktail-list');
    const empty = el('cocktail-empty');
    grid.innerHTML = '<div class="loading-row"><div class="spinner"></div></div>';
    const perPage = isMobile() ? 30 : calcLayout('cocktail-list');
    const params = this._buildParams(page, perPage);
    try {
      const d = await get('/api/cocktails', params);
      const items = d.data || [];
      this.lastMeta = d.meta;
      if (!items.length) { grid.innerHTML = ''; empty.classList.remove('hidden'); this._renderPagination(); return; }
      empty.classList.add('hidden');
      grid.innerHTML = items.map(c => this._card(c)).join('');
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
        .filter(i => !i.optional)
        .map(i => escHtml(i.ingredient?.name || ''))
        .filter(Boolean)
        .join(' · ');
    } else {
      ingFull = (c.short_ingredients || []).map(escHtml).join(' · ');
    }
    const ingNames = ingFull.length > 100 ? ingFull.slice(0, 100).replace(/ ·[^·]*$/, '') + ' …' : ingFull;
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
    await Promise.all(items.map(async c => {
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
      } catch (e) { /* silent — card just stays without image/rating */ }
    }));
  },

  _renderPagination() {
    if (isMobile()) return;
    const m = this.lastMeta;
    const bar = el('cocktail-pagination');
    if (!m || m.last_page <= 1) { bar.innerHTML = ''; return; }
    const prev = m.current_page > 1 ? `<button class="btn btn-ghost" onclick="App.cocktails.load(${m.current_page - 1})">‹ Prev</button>` : '<button class="btn btn-ghost" style="visibility:hidden">‹ Prev</button>';
    const next = m.current_page < m.last_page ? `<button class="btn btn-ghost" onclick="App.cocktails.load(${m.current_page + 1})">Next ›</button>` : '<button class="btn btn-ghost" style="visibility:hidden">Next ›</button>';
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
        el('cocktail-list').insertAdjacentHTML('beforeend', items.map(c => this._card(c)).join(''));
        this._enrichCards(items);
      }
    } catch (e) { /* silent */ }
    finally { this._loadingMore = false; }
  },

  async open(id) {
    this.currentId = id;
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
        get(`/api/cocktails/${id}`)
      ]);
      const data = cocktailResp.data;
      this.currentData = data;
      this._cache.set(id, data);
      if (this.currentId === id) this._renderDetail(data);
    } catch (e) {
      if (!cached) el('detail-body').innerHTML = `<p style="color:#f87171">${escHtml(e.message)}</p>`;
    }
  },

  toggleUnit() {
    UnitPref.toggle();
    el('unit-toggle-btn').textContent = UnitPref.get();
    if (this.currentData) this._renderDetail(this.currentData);
  },

  _renderDetail(c) {
    el('detail-title').textContent = c.name;
    el('detail-fav-btn').textContent = c.is_favorited ? '★' : '☆';
    el('unit-toggle-btn').textContent = UnitPref.get();

    const ings = (c.ingredients || []).map(i => {
      const ingId = i.ingredient_id ?? i.ingredient?.id;
      const onShelf = isOnShelf(ingId, i.ingredient);
      const dot = `<span class="ing-dot ${onShelf ? 'ing-dot-on' : 'ing-dot-off'}" title="${onShelf ? 'On shelf' : 'Not on shelf'}"></span>`;
      const { amount: amt, unit: unt } = UnitPref.convert(i.amount, i.units);
      const amtStr = i.amount ? `${amt} ${unt}`.trim() : '';
      return `<div class="ingredient-row">
        ${dot}
        <span class="ing-amount">${escHtml(amtStr)}</span>
        <span class="ing-name">${escHtml(i.name || i.ingredient?.name || '')}</span>
      </div>`;
    }).join('');

    const tags = (c.tags || []).map(t => `<span class="tag">${escHtml(t.name || t)}</span>`).join('');

    const userRating  = c.rating?.user_rating ?? 0;
    const avgRating   = c.rating?.average ?? 0;
    const displayStars = userRating || Math.round(avgRating);
    const starsHtml   = [1,2,3,4,5].map(n =>
      `<span class="detail-rating-star ${n <= displayStars ? 'active' : ''}" onclick="App.cocktails.rate(${c.id},${n})">${n <= displayStars ? '★' : '☆'}</span>`
    ).join('');

    const imgHtml = c.images?.[0] ? `<img class="detail-image-side" src="/api/images/${c.images[0].id}/thumb" alt="${escHtml(c.name)}">` : '';
    el('detail-body').innerHTML = `
      <div class="detail-rating-row">
        ${starsHtml}
        ${avgRating > 0 ? `<span class="detail-rating-avg">avg ${avgRating.toFixed(1)}</span>` : ''}
      </div>
      <div class="detail-hero">
        ${imgHtml}
        <div class="detail-section" style="flex:1;min-width:0;margin-bottom:0">
          <div class="detail-meta">
            ${c.glass   ? `<span><strong>Glass:</strong> ${escHtml(c.glass.name || c.glass)}</span>` : ''}
            ${c.method  ? `<span><strong>Method:</strong> ${escHtml(c.method.name || c.method)}</span>` : ''}
            ${c.abv     ? `<span><strong>ABV:</strong> ${escHtml(c.abv)}%</span>` : ''}
          </div>
          ${tags ? `<div class="card-tags">${tags}</div>` : ''}
        </div>
      </div>
      <div class="detail-section"><h3>Ingredients</h3>${ings || '<p style="color:var(--text-dim)">None listed</p>'}</div>
      ${c.instructions ? `<div class="detail-section"><h3>Instructions</h3><p class="detail-instructions">${escHtml(c.instructions)}</p></div>` : ''}
      ${c.garnish ? `<div class="detail-section"><h3>Garnish</h3><p class="detail-instructions">${escHtml(c.garnish)}</p></div>` : ''}
      ${c.description ? `<div class="detail-section"><h3>Notes</h3><p class="detail-instructions">${escHtml(c.description)}</p></div>` : ''}
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
    } catch (e) { Toast.err(e.message); }
  },

  async rate(id, stars) {
    if ((this.currentData?.rating?.user_rating ?? 0) === stars) {
      return this.clearRate(id);
    }
    try {
      await post(`/api/cocktails/${id}/ratings`, { rating: stars });
      await this._refreshRating(id, stars);
      Toast.show(`Rated ${stars} ★`);
    } catch (e) { Toast.err(e.message); }
  },

  async clearRate(id) {
    try {
      await del(`/api/cocktails/${id}/ratings`);
      await this._refreshRating(id, 0);
      Toast.show('Rating cleared');
    } catch (e) { Toast.err(e.message); }
  },

  async _refreshRating(id, userRating) {
    const fresh = await get(`/api/cocktails/${id}`);
    const rating = fresh.data?.rating || {};
    rating.user_rating = userRating;
    if (this.currentData) this.currentData.rating = rating;
    if (this._cache.has(id)) this._cache.get(id).rating = rating;

    const avgRating   = rating.average ?? 0;
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
        'beforeend', `<span class="detail-rating-avg">avg ${avgRating.toFixed(1)}</span>`
      );
    }
    const ratingSlot = el(`crating-${id}`);
    if (ratingSlot) {
      const cardStars = Math.round(avgRating);
      ratingSlot.innerHTML = cardStars > 0
        ? `<span class="rating-stars">${'★'.repeat(cardStars)}${'☆'.repeat(5 - cardStars)}</span><span class="rating-num">${avgRating.toFixed(1)}</span>`
        : '';
    }
  },

  editCurrent() {
    if (this.currentData) this.showEdit(this.currentData);
  },

  showCreate() {
    this._showForm(null);
  },

  showEdit(c) {
    this._showForm(c);
  },

  _showForm(c) {
    const title = c ? `Edit: ${c.name}` : 'New Cocktail';
    Modal.open(title,
      `<div class="form-group"><label class="form-label">Name *</label>
        <input class="text-input" id="cf-name" value="${escHtml(c?.name || '')}" placeholder="Cocktail name"></div>
      <div class="form-row">
        <div class="form-group"><label class="form-label">Glass</label>
          <input class="text-input" id="cf-glass" value="${escHtml(c?.glass?.name || '')}" placeholder="e.g. Rocks"></div>
        <div class="form-group"><label class="form-label">Method</label>
          <input class="text-input" id="cf-method" value="${escHtml(c?.method?.name || '')}" placeholder="e.g. Stirred"></div>
      </div>
      <div class="form-group"><label class="form-label">Instructions</label>
        <textarea class="text-input" id="cf-instructions">${escHtml(c?.instructions || '')}</textarea></div>
      <div class="form-group"><label class="form-label">Garnish</label>
        <input class="text-input" id="cf-garnish" value="${escHtml(c?.garnish || '')}" placeholder="Optional garnish"></div>
      <div class="form-group"><label class="form-label">Tags (comma-separated)</label>
        <input class="text-input" id="cf-tags" value="${(c?.tags || []).map(t => t.name || t).join(', ')}"></div>`,
      `<button class="btn btn-ghost" onclick="App.modal.close()">Cancel</button>
       <button class="btn btn-primary" onclick="App.cocktails._submitForm(${c?.id || 'null'})">${c ? 'Save' : 'Create'}</button>`
    );
    el('cf-name').focus();
  },

  async _submitForm(id) {
    const name = el('cf-name').value.trim();
    if (!name) { Toast.err('Name is required'); return; }
    const body = {
      name,
      instructions: el('cf-instructions').value.trim(),
      garnish:       el('cf-garnish').value.trim(),
      tags:          el('cf-tags').value.split(',').map(t => t.trim()).filter(Boolean),
    };
    try {
      if (id) {
        await put(`/api/cocktails/${id}`, body);
        Toast.show('Cocktail updated');
        this.open(id);
      } else {
        const d = await post('/api/cocktails', body);
        Toast.show('Cocktail created');
        this.load();
        if (d.data?.id) this.open(d.data.id);
      }
      Modal.close();
    } catch (e) { Toast.err(e.message); }
  },

  async deleteCurrent() {
    if (!this.currentId) return;
    if (!confirm(`Delete "${this.currentData?.name}"?`)) return;
    try {
      await del(`/api/cocktails/${this.currentId}`);
      Toast.show('Deleted');
      Nav.go('cocktails');
      this.load();
    } catch (e) { Toast.err(e.message); }
  }
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
      this._allItems = (d.data || []).map(c => ({ ...c, is_favorited: true }));
      await this._render();
    } catch (e) {
      grid.innerHTML = '';
      el('favorites-empty').classList.remove('hidden');
      el('favorites-empty').querySelector('p').textContent = e.message;
    }
  },

  async _render() {
    const grid  = el('favorites-list');
    const empty = el('favorites-empty');
    let items = [...this._allItems];

    if (this.shelfOnly && items.length) {
      try {
        const d = await get('/api/cocktails', { 'filter[on_shelf]': true, per_page: 500 });
        const shelfIds = new Set((d.data || []).map(c => c.id));
        items = items.filter(c => shelfIds.has(c.id));
      } catch (e) { /* fall back to unfiltered on error */ }
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
      items.sort((a, b) => this.sortDir === 'asc'
        ? a.name.localeCompare(b.name)
        : b.name.localeCompare(a.name));
    }

    empty.classList.add('hidden');
    grid.innerHTML = items.map(c => Cocktails._card(c)).join('');

    await Cocktails._enrichCards(items);

    if (this.sortBy === 'rating') {
      const cards = [...grid.children];
      cards.sort((a, b) => {
        const rA = Cocktails._cache.get(parseInt(a.dataset.id))?.rating?.average ?? 0;
        const rB = Cocktails._cache.get(parseInt(b.dataset.id))?.rating?.average ?? 0;
        const rCmp = this.sortDir === 'desc' ? rB - rA : rA - rB;
        if (rCmp !== 0) return rCmp;
        return (a.querySelector('.card-name')?.textContent ?? '').localeCompare(b.querySelector('.card-name')?.textContent ?? '');
      });
      grid.innerHTML = '';
      cards.forEach(c => grid.appendChild(c));
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
    const grid  = el('ingredient-list');
    const empty = el('ingredient-empty');
    grid.innerHTML = '<div class="loading-row"><div class="spinner"></div></div>';
    const params = { page, per_page: isMobile() ? 30 : calcLayout('ingredient-list') };
    if (this.query) params['filter[name]'] = this.query;
    params['sort'] = this.sortBy === 'name'
      ? (this.sortDir === 'desc' ? '-name' : 'name')
      : (this.sortDir === 'desc' ? `-${this.sortBy},name` : `${this.sortBy},name`);
    try {
      const d = await get('/api/ingredients', params);
      const items = d.data || [];
      this.lastMeta = d.meta;
      if (!items.length) { grid.innerHTML = ''; empty.classList.remove('hidden'); this._renderPagination(); return; }
      empty.classList.add('hidden');
      items.forEach(i => {
        this._shelfState.set(i.id, !!i.in_bar_shelf);
        this._cartState.set(i.id, !!i.in_shopping_list);
        if (i.in_bar_shelf) State.shelfIds.add(i.id);
      });
      grid.innerHTML = items.map(i => this._card(i)).join('');
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
    const inCart  = this._cartState.get(i.id);
    return `<div class="card row-layout" onclick="if(!event.target.closest('.ing-actions')) App.ingredients.showEdit(${i.id})">
      <div class="card-thumb-slot" id="ithumb-${i.id}"></div>
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
    await Promise.all(items.map(async i => {
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
      } catch (e) { /* silent */ }
    }));
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
        btn.className   = 'ing-action-btn' + (now ? ' shelf-active' : '');
        btn.title       = now ? 'Remove from bar shelf' : 'Add to bar shelf';
      }
      Toast.show(onShelf ? 'Removed from shelf' : 'Added to shelf');
    } catch (e) { Toast.err(e.message); }
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
        btn.className   = 'ing-action-btn' + (now ? ' cart-active' : '');
        btn.title       = now ? 'Remove from shopping list' : 'Add to shopping list';
      }
      Toast.show(inCart ? 'Removed from shopping list' : 'Added to shopping list');
    } catch (e) { Toast.err(e.message); }
  },

  _renderPagination() {
    const m = this.lastMeta;
    const bar = el('ingredient-pagination');
    if (!m || m.last_page <= 1) { bar.innerHTML = ''; return; }
    const prev = m.current_page > 1 ? `<button class="btn btn-ghost" onclick="App.ingredients.load(${m.current_page - 1})">‹ Prev</button>` : '<button class="btn btn-ghost" style="visibility:hidden">‹ Prev</button>';
    const next = m.current_page < m.last_page ? `<button class="btn btn-ghost" onclick="App.ingredients.load(${m.current_page + 1})">Next ›</button>` : '<button class="btn btn-ghost" style="visibility:hidden">Next ›</button>';
    bar.innerHTML = `${prev}<span>${m.current_page} / ${m.last_page}</span>${next}`;
  },

  showCreate() {
    this._showForm(null);
  },

  async showEdit(id) {
    const cached = this._cache.get(id);
    if (cached) { this._showForm(cached); return; }
    Modal.open('Loading…', '<div class="loading-row"><div class="spinner"></div></div>', '');
    try {
      const d = await get(`/api/ingredients/${id}`);
      this._cache.set(id, d.data);
      this._showForm(d.data);
    } catch (e) { Modal.close(); Toast.err(e.message); }
  },

  _showForm(i) {
    const title = i ? `Edit: ${i.name}` : 'New Ingredient';
    Modal.open(title,
      `<div class="form-group"><label class="form-label">Name *</label>
        <input class="text-input" id="if-name" value="${escHtml(i?.name || '')}" placeholder="Ingredient name"></div>
      <div class="form-group"><label class="form-label">Category</label>
        <input class="text-input" id="if-category" value="${escHtml(i?.category?.name || '')}" placeholder="e.g. Spirits"></div>
      <div class="form-group"><label class="form-label">Color (hex)</label>
        <input class="text-input" id="if-color" value="${escHtml(i?.color || '')}" placeholder="#ffffff"></div>
      <div class="form-group"><label class="form-label">Description</label>
        <textarea class="text-input" id="if-desc">${escHtml(i?.description || '')}</textarea></div>`,
      `<button class="btn btn-ghost" onclick="App.modal.close()">Cancel</button>
       ${i ? `<button class="btn btn-danger" onclick="App.ingredients._delete(${i.id})">Delete</button>` : ''}
       <button class="btn btn-primary" onclick="App.ingredients._submit(${i?.id || 'null'})">${i ? 'Save' : 'Create'}</button>`
    );
    el('if-name').focus();
  },

  async _submit(id) {
    const name = el('if-name').value.trim();
    if (!name) { Toast.err('Name is required'); return; }
    const body = {
      name,
      description: el('if-desc').value.trim(),
      color: el('if-color').value.trim(),
    };
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
    } catch (e) { Toast.err(e.message); }
  },

  async _delete(id) {
    if (!confirm('Delete this ingredient?')) return;
    try {
      await del(`/api/ingredients/${id}`);
      this._cache.delete(id);
      Toast.show('Deleted');
      Modal.close();
      this.load(this.page);
    } catch (e) { Toast.err(e.message); }
  }
};

// ── Tokens ─────────────────────────────────────────────────────────────────

const Tokens = {
  async load() {
    const grid  = el('token-list');
    const empty = el('token-empty');
    grid.innerHTML = '<div class="loading-row"><div class="spinner"></div></div>';
    try {
      const d = await get('/api/tokens');
      const items = d.data || [];
      if (!items.length) { grid.innerHTML = ''; empty.classList.remove('hidden'); return; }
      empty.classList.add('hidden');
      grid.innerHTML = items.map(t => `
        <div class="card shelf-card">
          <div class="card-name">${escHtml(t.token_name || t.name)}</div>
          <div class="card-sub">Abilities: ${escHtml(t.abilities?.join(', ') || 'none')}</div>
          <div class="card-sub">Last used: ${t.last_used_at ? new Date(t.last_used_at).toLocaleDateString() : 'Never'}</div>
          <button class="remove-btn" onclick="App.tokens.delete(${t.id})" title="Revoke token">✕</button>
        </div>`).join('');
    } catch (e) {
      grid.innerHTML = '';
      empty.classList.remove('hidden');
      empty.querySelector('p').textContent = e.message;
    }
  },

  showCreate() {
    Modal.open('New API Token',
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
    const abilities = el('tf-abilities').value.split(',').map(s => s.trim()).filter(Boolean);
    if (!name) { Toast.err('Name is required'); return; }
    try {
      const d = await post('/api/tokens', { name, abilities });
      const plainToken = d.data?.token;
      Modal.open('Token Created',
        `<p style="font-size:0.9rem;margin-bottom:12px">Copy this token now. It will not be shown again!</p>
         <div class="card" style="background:var(--bg-deep);cursor:text;user-select:all;word-break:break-all;font-family:monospace;font-size:0.85rem;padding:12px;border:1px solid var(--accent)">
           ${escHtml(plainToken)}
         </div>`,
        `<button class="btn btn-primary" onclick="App.modal.close(); App.tokens.load()">I have copied it</button>`
      );
    } catch (e) { Toast.err(e.message); }
  },

  async delete(id) {
    if (!confirm('Are you sure you want to revoke this token?')) return;
    try {
      await del(`/api/tokens/${id}`);
      Toast.show('Token revoked');
      this.load();
    } catch (e) { Toast.err(e.message); }
  }
};

// ── Auth ───────────────────────────────────────────────────────────────────

const Auth = {
  async login() {
    const email = el('login-email').value.trim();
    const password = el('login-pass').value.trim();
    const msg = el('login-msg');
    if (!email || !password) { msg.textContent = 'Enter email and password'; return; }
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
    } catch (e) { Toast.err(e.message); }
  }
};

// ── Users ──────────────────────────────────────────────────────────────────

const Users = {
  async load() {
    const grid  = el('user-list');
    const empty = el('user-empty');
    grid.innerHTML = '<div class="loading-row"><div class="spinner"></div></div>';
    try {
      const d = await get('/api/users');
      const items = d.data || [];
      if (!items.length) { grid.innerHTML = ''; empty.classList.remove('hidden'); return; }
      empty.classList.add('hidden');
      grid.innerHTML = items.map(u => `
        <div class="card shelf-card">
          <div class="card-name">${escHtml(u.name)}</div>
          <div class="card-sub">${escHtml(u.email)}</div>
          <div class="card-sub">Role: ${u.is_admin ? 'Admin' : 'User'}</div>
          <button class="remove-btn" onclick="App.users.delete(${u.id})" title="Delete user">✕</button>
        </div>`).join('');
    } catch (e) {
      grid.innerHTML = '';
      empty.classList.remove('hidden');
      empty.querySelector('p').textContent = e.message;
    }
  },

  showCreate() {
    Modal.open('New User',
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
    if (!name || !email || !password) { Toast.err('All fields are required'); return; }
    try {
      await post('/api/users', { name, email, password });
      Toast.show('User created');
      Modal.close();
      this.load();
    } catch (e) { Toast.err(e.message); }
  },

  async delete(id) {
    if (!confirm('Are you sure you want to delete this user?')) return;
    try {
      await del(`/api/users/${id}`);
      Toast.show('User deleted');
      this.load();
    } catch (e) { Toast.err(e.message); }
  }
};

// ── Shopping List ──────────────────────────────────────────────────────────

const ShoppingList = {
  async load() {
    const grid  = el('shopping-list-items');
    const empty = el('shopping-list-empty');
    grid.innerHTML = '<div class="loading-row"><div class="spinner"></div></div>';
    try {
      const d = await get('/api/shopping-list');
      const items = d.data || [];
      if (!items.length) { grid.innerHTML = ''; empty.classList.remove('hidden'); return; }
      empty.classList.add('hidden');
      grid.innerHTML = items.map(item => {
        const ing = item.ingredient;
        const onShelf = State.shelfIds.has(ing.id);
        return `<div class="card row-layout shelf-card">
          <div class="card-content">
            <div class="card-name">${escHtml(ing.name)}</div>
            ${item.quantity ? `<div class="card-sub">Qty: ${item.quantity}</div>` : ''}
          </div>
          ${!onShelf ? `<button class="ing-action-btn" style="flex-shrink:0"
            onclick="App.shoppingList.addToShelf(${ing.id}, '${escHtml(ing.name)}')"
            title="Add to bar shelf">+ shelf</button>` : ''}
          <button class="remove-btn" style="position:static;margin-left:${onShelf ? 'auto' : '6px'}"
            onclick="App.shoppingList.remove(${ing.id})" title="Remove from list">✕</button>
        </div>`;
      }).join('');
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
    } catch (e) { Toast.err(e.message); }
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
    } catch (e) { Toast.err(e.message); }
  },

  async clearAll() {
    if (!confirm('Remove all items from your shopping list?')) return;
    try {
      const d = await get('/api/shopping-list');
      const ids = (d.data || []).map(i => ({ id: i.ingredient.id }));
      if (!ids.length) return;
      await post('/api/shopping-list/batch-delete', { ingredients: ids });
      // Reset any visible ingredient card buttons
      ids.forEach(({ id }) => {
        const btn = el(`icart-${id}`);
        if (btn) { btn.textContent = '+ list'; btn.className = 'ing-action-btn'; }
        Ingredients._cartState.set(id, false);
      });
      Toast.show('Shopping list cleared');
      this.load();
    } catch (e) { Toast.err(e.message); }
  }
};

// ── App bootstrap ──────────────────────────────────────────────────────────


const App = {
  nav:          Nav,
  modal:        Modal,
  auth:         Auth,
  shelf:        Shelf,
  cocktails:    Cocktails,
  favorites:    Favorites,
  ingredients:  Ingredients,
  shoppingList: ShoppingList,
  tokens:       Tokens,
  users:        Users,
  settings:     Settings,

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
      el('shelf-search').addEventListener('input', debounce(e => Shelf.filter(e.target.value), 250));
      el('cocktail-search').addEventListener('input', debounce(e => {
        Cocktails.query = e.target.value;
        Cocktails.load(1);
      }, 350));
      el('ingredient-search').addEventListener('input', debounce(e => {
        Ingredients.query = e.target.value;
        Ingredients.load(1);
      }, 350));

      // Wire ingredient filter autocomplete
      const ingFilterInput = el('ing-filter-input');
      const ingAutoList    = el('ing-autocomplete');

      el('ing-token-box').addEventListener('click', () => ingFilterInput.focus());

      ingFilterInput.addEventListener('input', debounce(async () => {
        const q = ingFilterInput.value.trim();
        if (q.length < 1) { ingAutoList.classList.add('hidden'); return; }
        try {
          const d = await get('/api/ingredients', { 'filter[name]': q, per_page: 20 });
          const items = (d.data || []).filter(i =>
            !Cocktails.ingredientFilter.some(f => f.id === i.id)
          );
          Cocktails._acHighlight = -1;
          ingAutoList.innerHTML = '';
          if (!items.length) { ingAutoList.classList.add('hidden'); return; }
          items.forEach(ing => {
            const li = document.createElement('li');
            li.className = 'autocomplete-item';
            li.innerHTML = `<div class="ac-ing-img" id="ac-img-${ing.id}"><span class="ac-ing-placeholder">🍶</span></div><span>${escHtml(ing.name)}</span>`;
            li.addEventListener('mousedown', e => {
              e.preventDefault();
              Cocktails._selectIngredient({ id: ing.id, name: ing.name });
            });
            ingAutoList.appendChild(li);
          });
          ingAutoList.classList.remove('hidden');

          // Enrich each row with an image, using the ingredient detail cache when warm
          items.forEach(async ing => {
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
            } catch (e) { /* silent */ }
          });
        } catch (e) { /* silent */ }
      }, 250));

      ingFilterInput.addEventListener('keydown', e => {
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

      window.addEventListener('resize', debounce(() => {
        if (isMobile()) return;
        const view = Nav.current;
        if (view === 'cocktails')    Cocktails.load(Cocktails.page);
        else if (view === 'ingredients') Ingredients.load(Ingredients.page);
        else if (view === 'favorites')   Favorites.load();
      }, 400));

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
      sel.innerHTML = bars.map(b => `<option value="${b.id}" ${b.id == selectedId ? 'selected' : ''}>${escHtml(b.name)}</option>`).join('');
      if (!selectedId && bars.length) {
        el('cfg-bar').value = bars[0].id;
        this.saveBar();
      }
    } catch (e) { /* silent */ }
  },

  async loadVersion() {
    try {
      const d = await get('/api/server/version');
      el('server-version').textContent = `API Version: ${d.data?.version || 'Unknown'}`;
    } catch (e) {
      el('server-version').textContent = 'API Version: Error';
    }
  }
};

document.addEventListener('DOMContentLoaded', () => App.init());
