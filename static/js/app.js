/* ============================================================
   Crypto Portfolio Tracker — Alpine.js App
   ============================================================ */

const API = '/api';

// ── Utility helpers ──────────────────────────────────────────────────────────

function fmtUSD(n) {
  if (n == null) return '—';
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 }).format(n);
}

function fmtPct(n) {
  if (n == null) return '—';
  return (n >= 0 ? '+' : '') + n.toFixed(2) + '%';
}

function fmtAmount(n) {
  if (n == null) return '—';
  return n.toLocaleString('en-US', { maximumFractionDigits: 8 });
}

function _dataScore(c) {
  let s = 0;
  if (c.last != null)       s++;
  if (c.mktCap != null)     s++;
  if (c.vol90d != null)     s++;
  if (c.vol180d != null)    s++;
  if (c.vol365d != null)    s++;
  if (c.high != null)       s++;
  if (c.low != null)        s++;
  if (c.circulating != null) s++;
  if (c.change1_5y != null) s++;
  return s;
}

function fmtMktCap(n) {
  if (n == null) return '—';
  if (n >= 1e12) return '$' + (n / 1e12).toFixed(2) + 'T';
  if (n >= 1e9)  return '$' + (n / 1e9).toFixed(2) + 'B';
  if (n >= 1e6)  return '$' + (n / 1e6).toFixed(1) + 'M';
  return '$' + n.toLocaleString('en-US', { maximumFractionDigits: 0 });
}

function debounce(fn, ms = 350) {
  let t; return function(...a) { clearTimeout(t); t = setTimeout(() => fn.apply(this, a), ms); };
}

// ── localStorage TTL cache helpers ───────────────────────────────────────────

function lsSet(key, value, ttlSeconds = null) {
  try {
    localStorage.setItem(key, JSON.stringify({
      v:   value,
      exp: ttlSeconds ? Date.now() + ttlSeconds * 1000 : null,
    }));
  } catch {}
}

function lsGet(key) {
  try {
    const item = JSON.parse(localStorage.getItem(key));
    if (!item) return null;
    if (item.exp && Date.now() > item.exp) { localStorage.removeItem(key); return null; }
    return item.v;
  } catch { return null; }
}

// ── API client ───────────────────────────────────────────────────────────────

async function apiFetch(path, opts = {}) {
  const token = localStorage.getItem('token');
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(API + path, { ...opts, headers });
  if (res.status === 401) { localStorage.removeItem('token'); window.location.reload(); }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const e = new Error(err.detail || 'Request failed');
    e.status = res.status;
    e.headers = res.headers;
    throw e;
  }
  if (res.status === 204) return null;
  return res.json();
}

// ── Toast store ──────────────────────────────────────────────────────────────

document.addEventListener('alpine:init', () => {
  Alpine.store('toast', {
    items: [],
    show(msg, type = 'success') {
      const id = Date.now();
      this.items.push({ id, msg, type });
      setTimeout(() => { this.items = this.items.filter(i => i.id !== id); }, 3500);
    },
  });

  // ── Auth store ──────────────────────────────────────────────────────────────
  Alpine.store('auth', {
    token: localStorage.getItem('token'),
    user: null,

    get isLoggedIn() { return !!this.token; },

    async init() {
      if (this.token) {
        try { this.user = await apiFetch('/auth/me'); }
        catch { this.logout(); }
      }
    },

    async login(username, password) {
      const body = new URLSearchParams({ username, password });
      const res = await fetch(API + '/auth/token', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body,
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail); }
      const data = await res.json();
      this.token = data.access_token;
      localStorage.setItem('token', this.token);
      this.user = await apiFetch('/auth/me');
    },

    async register(username, email, password) {
      return await apiFetch('/auth/register', {
        method: 'POST',
        body: JSON.stringify({ username, email, password }),
      });
    },

    logout() {
      this.token = null;
      this.user = null;
      localStorage.removeItem('token');
    },
  });
});

// ── Login component ──────────────────────────────────────────────────────────

function loginApp() {
  return {
    tab: 'login',
    username: '', email: '', password: '',
    loading: false, error: '',

    // verification step
    verifyStep: false,
    pendingEmail: '',
    verifyCode: '',
    resendCooldown: 0,

    async submit() {
      this.error = '';
      this.loading = true;
      try {
        if (this.tab === 'login') {
          await Alpine.store('auth').login(this.username, this.password);
          window.location.reload();
        } else {
          const res = await Alpine.store('auth').register(this.username, this.email, this.password);
          this.pendingEmail = res.email;
          this.verifyStep = true;
        }
      } catch (e) {
        // Login blocked because account unverified
        if (e.message === 'Account not verified') {
          this.pendingEmail = e.headers?.get('X-Verify-Email') || this.email || this.username;
          this.verifyStep = true;
        } else {
          this.error = e.message;
        }
      } finally {
        this.loading = false;
      }
    },

    async submitVerify() {
      this.error = '';
      this.loading = true;
      try {
        const data = await apiFetch('/auth/verify', {
          method: 'POST',
          body: JSON.stringify({ email: this.pendingEmail, code: this.verifyCode.trim() }),
        });
        Alpine.store('auth').token = data.access_token;
        localStorage.setItem('token', data.access_token);
        Alpine.store('auth').user = await apiFetch('/auth/me');
        window.location.reload();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.loading = false;
      }
    },

    async resendCode() {
      if (this.resendCooldown > 0) return;
      try {
        await apiFetch('/auth/resend', {
          method: 'POST',
          body: JSON.stringify({ email: this.pendingEmail }),
        });
        Alpine.store('toast').show('New code sent — check your email');
        this.resendCooldown = 60;
        const t = setInterval(() => {
          this.resendCooldown--;
          if (this.resendCooldown <= 0) clearInterval(t);
        }, 1000);
      } catch (e) {
        Alpine.store('toast').show(e.message, 'error');
      }
    },
  };
}

// ── Main dashboard app ───────────────────────────────────────────────────────

function dashApp() {
  return {
    page: 'dashboard',
    portfolios: [],
    activePortfolioId: null,
    portfolioDetail: null,
    loadingPortfolio: false,
    _refreshTimer: null,

    // Market page
    topCoins: [],
    filteredCoins: [],
    loadingMarket: false,
    coinSearch: '',
    priceChart: null,
    selectedChartCoin: null,

    // Add portfolio modal
    showAddPortfolio: false,
    newPortfolioName: '',

    // Add holding modal
    showAddHolding: false,
    holdingModalTab: 'search',
    holdingDropdownOpen: false,
    holdingSearch: '',
    holdingSearchResults: [],
    holdingDisplayCoins: [],
    holdingSearchLoading: false,
    selectedCoin: null,
    holdingAmount: '',
    holdingAvgPrice: '',
    addingHolding: false,

    // Wallet import
    walletAddress: '',
    walletTokens: [],
    walletLoading: false,
    walletError: '',
    walletImporting: false,

    // Charts
    pieChart: null,
    lineChart: null,

    // Hash Lookup
    lookupQuery: '',
    lookupLoading: false,
    lookupResult: null,
    lookupError: '',

    // Paxos
    paxosBalances: [],
    paxosPrices: [],
    paxosMarkets: [],
    paxosLoading: false,
    paxosError: '',
    _paxosCache: {},
    paxosPinned: null,

    // Marketplace
    marketplaceCoins: [],
    marketplaceLoading: false,
    marketplaceError: '',
    _marketplaceCache: {},
    mkPage: 1,
    mkPerPage: 50,
    mkSearch: '',
    mkSort: 'price_desc',
    mkPinned: null,

    async init() {
      await Alpine.store('auth').init();
      if (!Alpine.store('auth').isLoggedIn) return;
      await this.loadPortfolios();
      if (this.portfolios.length) {
        this.activePortfolioId = this.portfolios[0].id;
        await this.loadPortfolioDetail();
      }
      this.$watch('page', (p) => {
        if (p === 'market') this.loadMarket();
        if (p === 'marketplace') this.loadMarketplace();
      });

      // Auto-refresh portfolio prices every 60 seconds
      this._refreshTimer = setInterval(async () => {
        if (this.activePortfolioId && !this.loadingPortfolio) {
          try {
            this.portfolioDetail = await apiFetch(`/portfolios/${this.activePortfolioId}`);
            this.renderPieChart();
          } catch {}
        }
      }, 90_000);
      // pre-fetch coins for ticker strip — always use limit=200 as canonical set
      setTimeout(() => {
        if (this.topCoins.length < 200) {
          apiFetch('/coins/top?limit=200').then(c => { if (c) this.topCoins = c; }).catch(() => {});
        }
      }, 2000);
      this.$watch('holdingSearch', () => this._rebuildHoldingCoins());
      this.$watch('holdingSearchResults', () => this._rebuildHoldingCoins());
      this.$watch('topCoins', () => { this._rebuildHoldingCoins(); this._rebuildFilteredCoins(); });
      this.$watch('coinSearch', () => this._rebuildFilteredCoins());
    },

    // ── Portfolio ────────────────────────────────────────────────────────────

    async loadPortfolios() {
      this.portfolios = await apiFetch('/portfolios');
    },

    async selectPortfolio(id) {
      this.activePortfolioId = id;
      await this.loadPortfolioDetail();
    },

    async loadPortfolioDetail() {
      if (!this.activePortfolioId) return;
      this.loadingPortfolio = true;
      try {
        this.portfolioDetail = await apiFetch(`/portfolios/${this.activePortfolioId}`);
        await this.$nextTick();
        this.renderPieChart();
      } catch (e) {
        Alpine.store('toast').show(e.message, 'error');
      } finally {
        this.loadingPortfolio = false;
      }
    },

    async createPortfolio() {
      if (!this.newPortfolioName.trim()) return;
      try {
        const p = await apiFetch('/portfolios', {
          method: 'POST',
          body: JSON.stringify({ name: this.newPortfolioName }),
        });
        this.portfolios.push(p);
        this.activePortfolioId = p.id;
        await this.loadPortfolioDetail();
        this.showAddPortfolio = false;
        this.newPortfolioName = '';
        Alpine.store('toast').show('Portfolio created');
      } catch (e) {
        Alpine.store('toast').show(e.message, 'error');
      }
    },

    async deletePortfolio(id) {
      if (!confirm('Delete this portfolio and all its holdings?')) return;
      try {
        await apiFetch(`/portfolios/${id}`, { method: 'DELETE' });
        this.portfolios = this.portfolios.filter(p => p.id !== id);
        if (this.activePortfolioId === id) {
          this.activePortfolioId = this.portfolios[0]?.id || null;
          this.portfolioDetail = null;
          if (this.activePortfolioId) await this.loadPortfolioDetail();
        }
        Alpine.store('toast').show('Portfolio deleted');
      } catch (e) {
        Alpine.store('toast').show(e.message, 'error');
      }
    },

    // ── Holdings ─────────────────────────────────────────────────────────────

    async openAddHolding() {
      this._resetHoldingModal();
      this.showAddHolding = true;
      if (this.topCoins.length < 200) {
        try { this.topCoins = await apiFetch('/coins/top?limit=200'); } catch {}
      }
      this._rebuildHoldingCoins();
    },

    closeAddHolding() {
      this.showAddHolding = false;
      this._resetHoldingModal();
    },

    _resetHoldingModal() {
      this.holdingModalTab = 'search';
      this.holdingSearch = '';
      this.holdingSearchResults = [];
      this.selectedCoin = null;
      this.holdingAmount = '';
      this.holdingAvgPrice = '';
      this.holdingDropdownOpen = false;
      this.walletAddress = '';
      this.walletTokens = [];
      this.walletError = '';
    },

    async fetchWalletTokens() {
      const addr = this.walletAddress.trim();
      if (!addr) return;
      this.walletLoading = true;
      this.walletError = '';
      this.walletTokens = [];
      try {
        const tokens = await apiFetch(`/wallet/eth/${encodeURIComponent(addr)}`);
        this.walletTokens = tokens.map(t => ({ ...t, selected: t.matched }));
      } catch (e) {
        this.walletError = e.message;
      } finally {
        this.walletLoading = false;
      }
    },

    async importSelectedWalletTokens() {
      const toImport = this.walletTokens.filter(t => t.selected && t.matched);
      if (!toImport.length) return;
      this.walletImporting = true;
      let successCount = 0;
      for (const token of toImport) {
        try {
          await apiFetch(`/portfolios/${this.activePortfolioId}/holdings`, {
            method: 'POST',
            body: JSON.stringify({
              coingecko_id: token.coingecko_id,
              amount: token.amount,
              avg_buy_price: null,
            }),
          });
          successCount++;
        } catch (e) {
          if (!e.message.includes('already in portfolio')) {
            Alpine.store('toast').show(`Skipped ${token.symbol}: ${e.message}`, 'error');
          }
        }
      }
      this.walletImporting = false;
      if (successCount > 0) {
        await this.loadPortfolioDetail();
        this.closeAddHolding();
        Alpine.store('toast').show(`Imported ${successCount} holding${successCount > 1 ? 's' : ''}`);
      }
    },

    _rebuildHoldingCoins() {
      const q = this.holdingSearch.toLowerCase().trim();
      const top = this.topCoins.map(c => ({
        id: c.coingecko_id,
        name: c.name,
        symbol: c.symbol,
        thumb: c.image_url,
      }));
      const filtered = q
        ? top.filter(c => c.name.toLowerCase().includes(q) || c.symbol.toLowerCase().includes(q))
        : top;
      const ids = new Set(filtered.map(c => c.id));
      const extra = this.holdingSearchResults.filter(c => !ids.has(c.id));
      this.holdingDisplayCoins = [...filtered, ...extra];
    },

    searchHoldingCoins: debounce(async function(q) {
      // If user edits after picking a coin, invalidate the selection
      if (this.selectedCoin && q !== this.selectedCoin.name) this.selectedCoin = null;
      if (q.length < 2) { this.holdingSearchResults = []; return; }
      this.holdingSearchLoading = true;
      try {
        this.holdingSearchResults = await apiFetch(`/coins/search?q=${encodeURIComponent(q)}`);
      } finally {
        this.holdingSearchLoading = false;
      }
    }),

    selectHoldingCoin(coin) {
      this.selectedCoin = coin;
      this.holdingSearch = coin.name;
      this.holdingSearchResults = [];
      this.holdingDropdownOpen = false;
    },

    async addHolding() {
      if (!this.selectedCoin || !this.holdingAmount) return;
      this.addingHolding = true;
      try {
        await apiFetch(`/portfolios/${this.activePortfolioId}/holdings`, {
          method: 'POST',
          body: JSON.stringify({
            coingecko_id: this.selectedCoin.id,
            amount: parseFloat(this.holdingAmount),
            avg_buy_price: this.holdingAvgPrice ? parseFloat(this.holdingAvgPrice) : null,
          }),
        });
        await this.loadPortfolioDetail();
        this.closeAddHolding();
        Alpine.store('toast').show('Holding added');
      } catch (e) {
        Alpine.store('toast').show(e.message, 'error');
      } finally {
        this.addingHolding = false;
      }
    },

    async removeHolding(holdingId) {
      if (!confirm('Remove this holding?')) return;
      try {
        await apiFetch(`/portfolios/${this.activePortfolioId}/holdings/${holdingId}`, { method: 'DELETE' });
        await this.loadPortfolioDetail();
        Alpine.store('toast').show('Holding removed');
      } catch (e) {
        Alpine.store('toast').show(e.message, 'error');
      }
    },

    // ── Charts ───────────────────────────────────────────────────────────────

    renderPieChart() {
      const canvas = document.getElementById('pieChart');
      if (!canvas || !this.portfolioDetail?.holdings?.length) return;
      if (getComputedStyle(canvas).display === 'none') return;

      if (this.pieChart) this.pieChart.destroy();

      const holdings = this.portfolioDetail.holdings.filter(h => h.current_value_usd > 0);
      const labels = holdings.map(h => h.coin.name);
      const data = holdings.map(h => h.current_value_usd);
      const colors = [
        '#b44dff','#00e676','#ff3366','#cc77ff','#00bcd4',
        '#7c3aed','#39ff14','#ff6ec7','#a78bfa','#0ff',
      ];

      this.pieChart = new Chart(canvas, {
        type: 'doughnut',
        data: {
          labels,
          datasets: [{
            data,
            backgroundColor: colors.slice(0, data.length).map(c => c + 'cc'), // slight transparency
            borderColor: colors.slice(0, data.length),
            borderWidth: 2,
            hoverOffset: 10,
          }],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: {
              position: 'right',
              labels: { color: '#5c5280', boxWidth: 10, padding: 14, font: { size: 11, family: "'JetBrains Mono', monospace" } },
            },
            tooltip: {
              backgroundColor: '#0d0a1e',
              borderColor: '#261d4a',
              borderWidth: 1,
              titleColor: '#e8e0ff',
              bodyColor: '#b44dff',
              callbacks: {
                label: ctx => ` ${fmtUSD(ctx.raw)} (${(ctx.raw / ctx.dataset.data.reduce((a,b)=>a+b,0)*100).toFixed(1)}%)`,
              },
            },
          },
        },
      });
    },

    async renderPriceChart(coingeckoId, days = 30) {
      this.selectedChartCoin = coingeckoId;
      const canvas = document.getElementById('lineChart');
      if (!canvas) return;

      if (this.lineChart) this.lineChart.destroy();

      try {
        const data = await apiFetch(`/coins/${coingeckoId}/history?days=${days}`);
        const labels = data.prices.map(p => new Date(p.timestamp).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }));
        const prices = data.prices.map(p => p.price);

        this.lineChart = new Chart(canvas, {
          type: 'line',
          data: {
            labels,
            datasets: [{
              label: coingeckoId.toUpperCase(),
              data: prices,
              borderColor: '#b44dff',
              backgroundColor: 'rgba(180,77,255,0.08)',
              borderWidth: 2,
              pointRadius: 0,
              fill: true,
              tension: 0.3,
            }],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            scales: {
              x: {
                ticks: { color: '#5c5280', maxTicksLimit: 8, font: { size: 11 } },
                grid: { color: '#261d4a' },
              },
              y: {
                ticks: {
                  color: '#5c5280', font: { size: 11 },
                  callback: v => fmtUSD(v),
                },
                grid: { color: '#261d4a' },
              },
            },
            plugins: {
              legend: { display: false },
              tooltip: {
                callbacks: {
                  label: ctx => ` ${fmtUSD(ctx.raw)}`,
                },
              },
            },
          },
        });
      } catch (e) {
        const msg = e?.detail || e?.message || 'Failed to load price chart';
        Alpine.store('toast').show(msg, 'error');
      }
    },

    // ── Market ───────────────────────────────────────────────────────────────

    async loadMarket() {
      this.loadingMarket = true;
      try {
        if (this.topCoins.length < 200) {
          this.topCoins = await apiFetch('/coins/top?limit=200');
        }
      } catch (e) {
        Alpine.store('toast').show(e.message, 'error');
      } finally {
        this.loadingMarket = false;
      }
    },

    _rebuildFilteredCoins() {
      const q = this.coinSearch.toLowerCase();
      this.filteredCoins = q
        ? this.topCoins.filter(c => c.name.toLowerCase().includes(q) || c.symbol.toLowerCase().includes(q))
        : [...this.topCoins];
    },

    // ── Helpers ──────────────────────────────────────────────────────────────

    async lookupHash() {
      const q = this.lookupQuery.trim();
      if (!q) return;
      this.lookupLoading = true;
      this.lookupError = '';
      this.lookupResult = null;
      try {
        this.lookupResult = await apiFetch(`/lookup/${encodeURIComponent(q)}`);
      } catch (e) {
        this.lookupError = e.message;
      } finally {
        this.lookupLoading = false;
      }
    },

    // ── Paxos ─────────────────────────────────────────────────────────────────

    async loadPaxos() {
      if (this.paxosLoading) return;
      this.paxosLoading = true;
      this.paxosError = '';
      try {
        // ── Load localStorage caches ────────────────────────────────────────
        // Icons:      no expiry  — image URLs essentially never change
        // Markets:    7 days    — Paxos market list changes very rarely
        // 1Y ranges:  24 hours  — high/low + volatility from same CoinGecko data
        // Long range: 24 hours  — 1.5Y change from CryptoCompare
        let iconCache      = lsGet('icon_cache')  || {};
        let marketsCache   = lsGet('markets_cache');
        let yearlyCache    = lsGet('yearly_cache')   || {};
        let longRangeCache = lsGet('long_range_cache')     || {};

        // Only fetch topCoins if not already loaded
        if (this.topCoins.length < 200) {
          try { this.topCoins = await apiFetch('/coins/top?limit=200'); } catch {}
        }

        // Build symbol→coin lookup map once (avoids repeated .find() in row loops)
        const cgBySymbol = {};
        for (const c of this.topCoins) cgBySymbol[c.symbol.toUpperCase()] = c;

        // Skip cached endpoints — only hit API when cache is stale
        const [prices, freshMarkets, balances] = await Promise.all([
          apiFetch('/paxos/prices'),
          marketsCache ? Promise.resolve(null) : apiFetch('/paxos/markets').catch(() => null),
          apiFetch('/paxos/balances').catch(() => null),
        ]);

        // Persist fresh markets (7 days)
        if (freshMarkets) {
          marketsCache = freshMarkets;
          lsSet('markets_cache', freshMarkets, 7 * 24 * 3600);
        }

        const priceMap  = {};
        if (Array.isArray(prices)) prices.forEach(p => { priceMap[p.market] = p; });
        const usdMarkets = (Array.isArray(marketsCache) ? marketsCache.filter(m => m.quote_asset === 'USD') : [])
          .map(m => {
            const sym = m.base_asset.toUpperCase();
            const cg  = cgBySymbol[sym];
            if (cg?.image_url) iconCache[sym] = { url: cg.image_url, name: cg.name };
            else if (cg?.name && iconCache[sym]) iconCache[sym].name = cg.name;
            return { ...m, image: iconCache[sym]?.url || null };
          });

        lsSet('icon_cache', iconCache, null);

        this.paxosMarkets  = usdMarkets;
        this.paxosBalances = Array.isArray(balances) ? balances : [];

        // Build table rows immediately — 1Y High/Low filled from cache or left as null
        this.paxosPrices = usdMarkets.map(m => {
          const cached     = this._paxosCache[m.market] || {};
          const ticker     = priceMap[m.market] || {};
          const sym        = m.base_asset.toUpperCase();
          const cg         = cgBySymbol[sym];
          const paxosLast  = parseFloat(ticker.last_execution?.price);
          const cgPrice    = cg?.current_price_usd ?? null;
          const yearly     = yearlyCache[cg?.coingecko_id] || {};
          const lr         = longRangeCache[sym] || {};
          const fresh = {
            image:       iconCache[sym]?.url || null,
            coinName:    cg?.name ?? iconCache[sym]?.name ?? null,
            mktCap:      cg?.market_cap ?? null,
            change200d:  cg?.price_change_200d ?? null,
            change1y:    cg?.price_change_1y   ?? null,
            change1_5y:  lr.change1_5y ?? null,
            vol90d:      yearly.vol_90d  ?? null,
            vol180d:     yearly.vol_180d ?? null,
            vol365d:     yearly.vol_365d ?? null,
            last:        ((!isNaN(paxosLast) && paxosLast > 0) ? ticker.last_execution?.price : cgPrice) ?? null,
            bid:         ticker.best_bid?.price || null,
            ask:         ticker.best_ask?.price || null,
            spread:      (ticker.best_bid?.price && ticker.best_ask?.price)
                           ? (parseFloat(ticker.best_ask.price) - parseFloat(ticker.best_bid.price))
                           : null,
            high:        yearly.high_1y ?? null,
            low:         yearly.low_1y  ?? null,
            circulating: cg?.circulating_supply ?? null,
            hardCap:     HARD_CAPS[sym] !== undefined ? HARD_CAPS[sym] : (cg?.max_supply ?? null),
          };
          const merged = {};
          for (const key of Object.keys(fresh)) merged[key] = fresh[key] ?? cached[key] ?? null;
          this._paxosCache[m.market] = { ...cached, ...merged };
          return { ...m, ...merged };
        }).sort((a, b) => (parseFloat(b.last) || 0) - (parseFloat(a.last) || 0));

        // Fetch 1Y ranges in background — only for Paxos market coins not yet cached
        const paxosCgIds = usdMarkets
          .map(m => cgBySymbol[m.base_asset.toUpperCase()]?.coingecko_id)
          .filter(id => id && !yearlyCache[id]);
        if (paxosCgIds.length) {
          apiFetch(`/coins/yearly-ranges?ids=${paxosCgIds.join(',')}`).then(fresh => {
            if (!fresh || !Object.keys(fresh).length) return;
            yearlyCache = { ...yearlyCache, ...fresh };
            lsSet('yearly_cache', yearlyCache, 24 * 3600);
            this.paxosPrices = this.paxosPrices.map(p => {
              const cg = cgBySymbol[p.base_asset.toUpperCase()];
              const yr = fresh[cg?.coingecko_id];
              if (!yr) return p;
              const updated = { ...p, high: yr.high_1y ?? p.high, low: yr.low_1y ?? p.low, vol90d: yr.vol_90d ?? p.vol90d, vol180d: yr.vol_180d ?? p.vol180d, vol365d: yr.vol_365d ?? p.vol365d };
              this._paxosCache[p.market] = { ...this._paxosCache[p.market], ...updated };
              return updated;
            });
          }).catch(() => {});
        }

        // Fetch 1.5Y & 3Y changes from CryptoCompare (served from server cache)
        const paxosSymsForLR = usdMarkets
          .map(m => m.base_asset.toUpperCase())
          .filter(s => !longRangeCache[s]);
        if (paxosSymsForLR.length) {
          apiFetch(`/cryptocompare/changes?symbols=${paxosSymsForLR.join(',')}&days=548`).then(fresh => {
            if (!fresh || !Object.keys(fresh).length) return;
            for (const [sym, data] of Object.entries(fresh)) {
              longRangeCache[sym] = { change1_5y: data[548] ?? null };
            }
            lsSet('long_range_cache', longRangeCache, 24 * 3600);
            this.paxosPrices = this.paxosPrices.map(p => {
              const lr = longRangeCache[p.base_asset.toUpperCase()];
              if (!lr) return p;
              const updated = { ...p, change1_5y: lr.change1_5y ?? p.change1_5y };
              this._paxosCache[p.market] = { ...this._paxosCache[p.market], ...updated };
              return updated;
            });
          }).catch(() => {});
        }

      } catch (e) {
        this.paxosError = e.message;
      } finally {
        this.paxosLoading = false;
      }
    },

    paxosCoinDescription(symbol) { return COIN_DESCRIPTIONS[symbol.toUpperCase()] || null; },

    coinCollateral(symbol) { return _collateralMap[symbol.toUpperCase()] || null; },

    volatilityLabel(vol) {
      if (vol == null) return null;
      if (vol < 0.20) return { label: 'Low',       cls: 'badge-green'  };
      if (vol < 0.55) return { label: 'Moderate',   cls: 'badge-yellow' };
      if (vol < 0.85) return { label: 'High',       cls: 'badge-orange'  };
      return              { label: 'Very High',  cls: 'badge-red-glow' };
    },

    coinFeatures(symbol) { return COIN_FEATURES[symbol.toUpperCase()] || null; },

    coinYieldTypes(symbol) { return COIN_YIELD_TYPES[symbol.toUpperCase()] || null; },


    paxosCoinImage(symbol) {
      const match = this.topCoins.find(c => c.symbol.toUpperCase() === symbol.toUpperCase());
      return match?.image_url || null;
    },

    // ── Marketplace ───────────────────────────────────────────────────────────

    async loadMarketplace() {
      if (this.marketplaceLoading) return;
      this.marketplaceLoading = true;
      this.marketplaceError = '';
      try {
        // Reuse shared caches
        let iconCache      = lsGet('icon_cache')  || {};
        let yearlyCache    = lsGet('yearly_cache')   || {};
        let longRangeCache = lsGet('long_range_cache')     || {};

        // Ensure topCoins are loaded
        if (this.topCoins.length < 200) {
          try { this.topCoins = await apiFetch('/coins/top?limit=200'); } catch {}
        }

        const cgBySymbol = {};
        for (const c of this.topCoins) cgBySymbol[c.symbol.toUpperCase()] = c;

        // All top coins — comprehensive market view
        const coins = this.topCoins
          .map(c => {
            const sym = c.symbol.toUpperCase();
            const yearly = yearlyCache[c.coingecko_id] || {};
            const lr     = longRangeCache[sym] || {};

            // Keep icon cache warm
            if (c.image_url) iconCache[sym] = { url: c.image_url, name: c.name };

            const fresh = {
              image:       c.image_url ?? iconCache[sym]?.url ?? null,
              coinName:    c.name ?? iconCache[sym]?.name ?? null,
              mktCap:      c.market_cap ?? null,
              base_asset:  sym,
              market:      sym + '/USD',
              change200d:  c.price_change_200d ?? null,
              change1y:    c.price_change_1y   ?? null,
              change1_5y:  lr.change1_5y ?? null,
              vol90d:      yearly.vol_90d  ?? null,
              vol180d:     yearly.vol_180d ?? null,
              vol365d:     yearly.vol_365d ?? null,
              last:        c.current_price_usd  ?? null,
              bid:         null,
              ask:         null,
              spread:      null,
              high:        yearly.high_1y ?? null,
              low:         yearly.low_1y  ?? null,
              circulating: c.circulating_supply ?? null,
              hardCap:     HARD_CAPS[sym] !== undefined ? HARD_CAPS[sym] : (c.max_supply ?? null),
            };
            const cached = this._marketplaceCache[sym] || {};
            const merged = {};
            for (const key of Object.keys(fresh)) merged[key] = fresh[key] ?? cached[key] ?? null;
            this._marketplaceCache[sym] = { ...cached, ...merged };
            return { ...merged };
          })
          .sort((a, b) => {
            const scoreA = _dataScore(a);
            const scoreB = _dataScore(b);
            if (scoreB !== scoreA) return scoreB - scoreA;
            return (b.last || 0) - (a.last || 0);
          });

        lsSet('icon_cache', iconCache, null);
        this.marketplaceCoins = coins;

        // Background-fetch 1Y ranges for uncached coins
        const mkIds = coins
          .map(c => cgBySymbol[c.base_asset]?.coingecko_id)
          .filter(id => id && !yearlyCache[id]);
        if (mkIds.length) {
          apiFetch(`/coins/yearly-ranges?ids=${mkIds.join(',')}`).then(fresh => {
            if (!fresh || !Object.keys(fresh).length) return;
            yearlyCache = { ...yearlyCache, ...fresh };
            lsSet('yearly_cache', yearlyCache, 24 * 3600);
            this.marketplaceCoins = this.marketplaceCoins.map(p => {
              const cg = cgBySymbol[p.base_asset];
              const yr = fresh[cg?.coingecko_id];
              if (!yr) return p;
              const updated = { ...p, high: yr.high_1y ?? p.high, low: yr.low_1y ?? p.low, vol90d: yr.vol_90d ?? p.vol90d, vol180d: yr.vol_180d ?? p.vol180d, vol365d: yr.vol_365d ?? p.vol365d };
              this._marketplaceCache[p.base_asset] = { ...this._marketplaceCache[p.base_asset], ...updated };
              return updated;
            }).sort((a, b) => {
              const sa = _dataScore(a), sb = _dataScore(b);
              if (sb !== sa) return sb - sa;
              return (b.last || 0) - (a.last || 0);
            });
          }).catch(() => {});
        }

        // Fetch 1.5Y & 3Y changes from CryptoCompare (served from server cache)
        const mkSymsForLR = coins
          .map(c => c.base_asset)
          .filter(s => !longRangeCache[s]);
        if (mkSymsForLR.length) {
          apiFetch(`/cryptocompare/changes?symbols=${mkSymsForLR.join(',')}&days=548`).then(fresh => {
            if (!fresh || !Object.keys(fresh).length) return;
            for (const [sym, data] of Object.entries(fresh)) {
              longRangeCache[sym] = { change1_5y: data[548] ?? null };
            }
            lsSet('long_range_cache', longRangeCache, 24 * 3600);
            this.marketplaceCoins = this.marketplaceCoins.map(p => {
              const lr = longRangeCache[p.base_asset];
              if (!lr) return p;
              const updated = { ...p, change1_5y: lr.change1_5y ?? p.change1_5y };
              this._marketplaceCache[p.base_asset] = { ...this._marketplaceCache[p.base_asset], ...updated };
              return updated;
            }).sort((a, b) => {
              const sa = _dataScore(a), sb = _dataScore(b);
              if (sb !== sa) return sb - sa;
              return (b.last || 0) - (a.last || 0);
            });
          }).catch(() => {});
        }

      } catch (e) {
        this.marketplaceError = e.message;
      } finally {
        this.marketplaceLoading = false;
        this.mkPage = 1;
      }
    },

    mkFilteredCoins() {
      const STABLES = STABLECOIN_SYMBOLS;
      let coins = this.marketplaceCoins;

      // Text search
      if (this.mkSearch.trim()) {
        const q = this.mkSearch.trim().toLowerCase();
        coins = coins.filter(c =>
          c.base_asset.toLowerCase().includes(q) ||
          (c.coinName || '').toLowerCase().includes(q)
        );
      }

      // Sort/filter by dropdown
      switch (this.mkSort) {
        case 'stablecoin':
          coins = coins.filter(c => STABLES.has(c.base_asset));
          break;
        case 'top10':
          coins = [...coins].sort((a, b) => (b.last || 0) - (a.last || 0)).slice(0, 10);
          break;
        case 'most_volatile':
          coins = [...coins].sort((a, b) => (b.vol90d || 0) - (a.vol90d || 0));
          break;
        case 'least_volatile':
          coins = [...coins].sort((a, b) => (a.vol90d || 999) - (b.vol90d || 999));
          break;
        case 'vol_low':
          coins = coins.filter(c => c.vol90d != null && c.vol90d < 0.20);
          break;
        case 'vol_moderate':
          coins = coins.filter(c => c.vol90d != null && c.vol90d >= 0.20 && c.vol90d < 0.55);
          break;
        case 'vol_high':
          coins = coins.filter(c => c.vol90d != null && c.vol90d >= 0.55 && c.vol90d < 0.85);
          break;
        case 'vol_very_high':
          coins = coins.filter(c => c.vol90d != null && c.vol90d >= 0.85);
          break;
        default: // price_desc
          coins = [...coins].sort((a, b) => {
            const sa = _dataScore(a), sb = _dataScore(b);
            if (sb !== sa) return sb - sa;
            return (b.last || 0) - (a.last || 0);
          });
          break;
      }

      // Float pinned coin to top
      if (this.mkPinned) {
        const idx = coins.findIndex(c => c.base_asset === this.mkPinned);
        if (idx > 0) {
          const [pinned] = coins.splice(idx, 1);
          coins.unshift(pinned);
        }
      }

      return coins;
    },

    mkPageCoins() {
      const filtered = this.mkFilteredCoins();
      const start = (this.mkPage - 1) * this.mkPerPage;
      return filtered.slice(start, start + this.mkPerPage);
    },

    mkTotalPages() {
      return Math.max(1, Math.ceil(this.mkFilteredCoins().length / this.mkPerPage));
    },

    fmtPaxosPrice(v) {
      if (v == null) return '—';
      const n = parseFloat(v);
      if (isNaN(n) || n === 0) return '—';
      if (n < 0.0001)  return '$' + n.toFixed(10).replace(/\.?0+$/, '');
      if (n < 0.01)    return '$' + n.toFixed(6).replace(/\.?0+$/, '');
      if (n < 1)       return '$' + n.toFixed(4);
      return fmtUSD(n);
    },

    paxosSpread(p) {
      if (p.spread == null) return '—';
      return fmtUSD(p.spread);
    },

    lookupConfidenceClass(c) {
      if (c === 'confirmed') return 'badge-green';
      if (c === 'likely')    return 'badge-yellow';
      return 'badge-muted';
    },

    lookupConfidenceLabel(c) {
      if (c === 'confirmed') return 'Confirmed';
      if (c === 'likely')    return 'Likely';
      return 'Format Match';
    },

    fmtUSD, fmtPct, fmtAmount,

    pnlClass(n) { return n == null ? '' : n >= 0 ? 'pos' : 'neg'; },

    logout() {
      clearInterval(this._refreshTimer);
      Alpine.store('auth').logout();
      window.location.reload();
    },
  };
}
