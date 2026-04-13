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

function debounce(fn, ms = 350) {
  let t; return function(...a) { clearTimeout(t); t = setTimeout(() => fn.apply(this, a), ms); };
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
      // pre-fetch coins for ticker strip — reuse topCoins if already populated
      setTimeout(() => {
        if (!this.topCoins.length) {
          apiFetch('/coins/top?limit=50').then(c => { if (c) this.topCoins = c; }).catch(() => {});
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
      if (!this.topCoins.length) {
        try { this.topCoins = await apiFetch('/coins/top?limit=100'); } catch {}
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
        this.topCoins = await apiFetch('/coins/top?limit=50');
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
        // Fetch a larger coin list to maximise image/price coverage
        if (this.topCoins.length < 200) {
          try { this.topCoins = await apiFetch('/coins/top?limit=200'); } catch {}
        }

        const [prices, markets, balances] = await Promise.all([
          apiFetch('/paxos/prices'),
          apiFetch('/paxos/markets'),
          apiFetch('/paxos/balances').catch(() => null),
        ]);

        const priceMap = {};
        if (Array.isArray(prices)) prices.forEach(p => { priceMap[p.market] = p; });
        const usdMarkets = (Array.isArray(markets) ? markets.filter(m => m.quote_asset === 'USD') : [])
          .map(m => {
            const cg = this.topCoins.find(c => c.symbol.toUpperCase() === m.base_asset.toUpperCase());
            return { ...m, image: cg?.image_url || null };
          });
        this.paxosMarkets = usdMarkets;
        this.paxosBalances = Array.isArray(balances) ? balances : [];
        this.paxosPrices  = usdMarkets.map(m => {
          const ticker = priceMap[m.market] || {};
          const cg = this.topCoins.find(c => c.symbol.toUpperCase() === m.base_asset.toUpperCase());
          const image = cg?.image_url || null;
          const paxosLast = parseFloat(ticker.last_execution?.price);
          const cgPrice = cg?.current_price_usd ?? null;
          const last = (!isNaN(paxosLast) && paxosLast > 0) ? ticker.last_execution?.price : cgPrice;
          const bid    = ticker.best_bid?.price || null;
          const ask    = ticker.best_ask?.price || null;
          const spread = (bid && ask) ? (parseFloat(ask) - parseFloat(bid)) : null;
          let high = parseFloat(ticker.last_day?.high) > 0 ? ticker.last_day?.high : null;
          let low  = parseFloat(ticker.last_day?.low)  > 0 ? ticker.last_day?.low  : null;
          // Derive approx 24h high/low from CoinGecko price change % when Paxos has no data
          if ((!high || !low) && cgPrice && cg?.price_change_24h != null) {
            const pct = cg.price_change_24h / 100;
            const open = cgPrice / (1 + pct);
            high = high || Math.max(cgPrice, open);
            low  = low  || Math.min(cgPrice, open);
          }
          return { ...m, image, last, bid, ask, spread, high, low };
        });
      } catch (e) {
        this.paxosError = e.message;
      } finally {
        this.paxosLoading = false;
      }
    },

    paxosCoinImage(symbol) {
      const match = this.topCoins.find(c => c.symbol.toUpperCase() === symbol.toUpperCase());
      return match?.image_url || null;
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
