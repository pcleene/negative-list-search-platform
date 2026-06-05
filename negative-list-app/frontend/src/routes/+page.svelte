<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import {
    postSearch,
    searchNegativeList,
    autocomplete,
    getStats,
    type SearchMode,
    type NegativeEntry,
    type DashboardStats,
    type ApiMeta,
    type PaginationInfo,
    type Facet,
  } from '$lib/api';

  // ─── State ────────────────────────────────────────────────────────
  let searchQuery = $state('');
  let searchMode: SearchMode = $state('fuzzy');
  let maxEdits = $state(1);
  let dobFilter = $state('');
  let nationalIdFilter = $state('');
  let showFilters = $state(false);
  let isSearching = $state(false);
  let searchError = $state('');

  // Results
  let searchResults: NegativeEntry[] = $state([]);
  let searchMeta: ApiMeta | null = $state(null);
  let maxScore = $state(1);

  // Pagination
  let pagination: PaginationInfo | null = $state(null);
  let currentPage = $state(1);

  // Facets
  let facets: Facet[] = $state([]);
  let selectedFilters: Record<string, string[]> = $state({});
  let expandedFacets: Set<string> = $state(new Set());
  let showFacetSidebar = $state(false);

  // Autocomplete
  let acResults: NegativeEntry[] = $state([]);
  let acVisible = $state(false);
  let acDebounceTimer: ReturnType<typeof setTimeout> | null = $state(null);

  // Dashboard stats
  let stats: DashboardStats | null = $state(null);

  // Drawers
  let showQueryDrawer = $state(false);

  // Track if we've done at least one search
  let hasSearched = $state(false);

  // ─── Derived ──────────────────────────────────────────────────────
  let activeFilterCount = $derived(
    Object.values(selectedFilters).reduce((sum, arr) => sum + arr.length, 0)
  );

  // ─── Currency Formatter ───────────────────────────────────────────
  const phpFormat = new Intl.NumberFormat('en-PH', {
    style: 'currency', currency: 'PHP', minimumFractionDigits: 0, maximumFractionDigits: 0
  });

  const compactPhp = new Intl.NumberFormat('en-PH', {
    style: 'currency', currency: 'PHP', notation: 'compact', maximumFractionDigits: 0
  });

  // ─── Helpers ──────────────────────────────────────────────────────
  function normalizeScore(score: number | undefined, mode: SearchMode): number {
    if (score === undefined) return 0;
    if (mode === 'semantic') return Math.round(score * 100);
    return maxScore > 0 ? Math.round((score / maxScore) * 100) : 0;
  }

  function riskColor(score: number): string {
    if (score > 0.7) return 'text-red-400 bg-red-500/20 border-red-500/50';
    if (score > 0.4) return 'text-amber-400 bg-amber-500/20 border-amber-500/50';
    return 'text-emerald-400 bg-emerald-500/20 border-emerald-500/50';
  }

  function reasonColor(code: string): string {
    const map: Record<string, string> = {
      LOAN_DEFAULT: 'bg-red-500/20 text-red-300 border-red-500/40',
      CC_CANCELLED: 'bg-orange-500/20 text-orange-300 border-orange-500/40',
      FRAUD_CONFIRMED: 'bg-rose-600/20 text-rose-300 border-rose-600/40',
      AML_FLAG: 'bg-purple-500/20 text-purple-300 border-purple-500/40',
      CHECK_FRAUD: 'bg-pink-500/20 text-pink-300 border-pink-500/40',
      IDENTITY_THEFT: 'bg-fuchsia-500/20 text-fuchsia-300 border-fuchsia-500/40',
      CYBER_FRAUD: 'bg-violet-500/20 text-violet-300 border-violet-500/40'
    };
    return map[code] || 'bg-slate-500/20 text-slate-300 border-slate-500/40';
  }

  function syntaxHighlightJson(obj: unknown): string {
    const json = JSON.stringify(obj, null, 2);
    return json
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"([^"]+)"(?=\s*:)/g, '<span class="json-key">"$1"</span>')
      .replace(/:\s*"([^"]*?)"/g, ': <span class="json-string">"$1"</span>')
      .replace(/:\s*(\d+\.?\d*)/g, ': <span class="json-number">$1</span>')
      .replace(/:\s*(true|false)/g, ': <span class="json-boolean">$1</span>')
      .replace(/:\s*(null)/g, ': <span class="json-null">$1</span>')
      .replace(/([[\]{}])/g, '<span class="json-bracket">$1</span>');
  }

  async function copyToClipboard(text: string) {
    try { await navigator.clipboard.writeText(text); } catch {}
  }

  // ─── State Persistence (only for back-navigation from profile) ──
  function saveSearchState(setRestoreFlag = false) {
    const state = { searchQuery, searchMode, maxEdits, dobFilter, nationalIdFilter, hasSearched };
    sessionStorage.setItem('mb-search-state', JSON.stringify(state));
    if (setRestoreFlag) {
      sessionStorage.setItem('mb-search-restore', '1');
    }
  }

  function restoreSearchState(): boolean {
    if (!sessionStorage.getItem('mb-search-restore')) {
      sessionStorage.removeItem('mb-search-state');
      return false;
    }
    sessionStorage.removeItem('mb-search-restore');
    const saved = sessionStorage.getItem('mb-search-state');
    if (!saved) return false;
    try {
      const state = JSON.parse(saved);
      searchQuery = state.searchQuery || '';
      searchMode = state.searchMode || 'fuzzy';
      maxEdits = state.maxEdits ?? 1;
      dobFilter = state.dobFilter || '';
      nationalIdFilter = state.nationalIdFilter || '';
      hasSearched = state.hasSearched || false;
      return hasSearched && searchQuery.trim().length > 0;
    } catch {
      return false;
    }
  }

  // ─── Search Logic ─────────────────────────────────────────────────
  async function doSearch(resetPage = true) {
    if (!searchQuery.trim()) return;
    acVisible = false;
    isSearching = true;
    searchError = '';

    if (resetPage) currentPage = 1;

    try {
      if (searchMode === 'fuzzy') {
        const resp = await postSearch({
          query: searchQuery.trim(),
          mode: 'fuzzy',
          max_edits: maxEdits,
          limit: 20,
          dob: dobFilter || undefined,
          national_id: nationalIdFilter || undefined,
          filters: Object.keys(selectedFilters).length > 0 ? selectedFilters : undefined,
          use_facets: true,
        });

        searchResults = resp.results;
        searchMeta = resp._meta;
        pagination = resp.pagination;
        facets = resp.facets;
      } else {
        const resp = await searchNegativeList({
          q: searchQuery.trim(),
          mode: 'semantic',
          limit: 20,
        });
        searchResults = resp.results;
        searchMeta = resp._meta;
        pagination = null;
        facets = [];
      }

      hasSearched = true;

      if (searchResults.length > 0) {
        maxScore = Math.max(...searchResults.map(r => r.score ?? 0));
      } else {
        maxScore = 1;
      }

      saveSearchState();
    } catch (err) {
      searchError = err instanceof Error ? err.message : 'Search failed';
      searchResults = [];
    } finally {
      isSearching = false;
    }
  }

  async function doAutocomplete(q: string) {
    if (!q.trim() || q.length < 2 || searchMode !== 'fuzzy') {
      acResults = [];
      acVisible = false;
      return;
    }
    try {
      const resp = await autocomplete(q.trim(), 8);
      acResults = resp.results;
      acVisible = acResults.length > 0;
    } catch {
      acResults = [];
      acVisible = false;
    }
  }

  function onSearchInput() {
    if (acDebounceTimer) clearTimeout(acDebounceTimer);
    acDebounceTimer = setTimeout(() => doAutocomplete(searchQuery), 200);
  }

  function selectAutoComplete(entry: NegativeEntry) {
    searchQuery = entry.fullName;
    acVisible = false;
    doSearch();
  }

  function handleSearchKeydown(e: KeyboardEvent) {
    if (e.key === 'Enter') { acVisible = false; doSearch(); }
    if (e.key === 'Escape') { acVisible = false; }
  }

  // ─── Pagination Handlers ──────────────────────────────────────────
  function handleNextPage() {
    if (!pagination?.hasMore) return;
    currentPage++;
    doSearch(false);
  }

  function handlePrevPage() {
    if (currentPage <= 1) return;
    currentPage--;
    doSearch(false);
  }

  // ─── Facet Handlers ───────────────────────────────────────────────
  function toggleFacetValue(field: string, value: string) {
    const current = selectedFilters[field] || [];
    if (current.includes(value)) {
      selectedFilters[field] = current.filter(v => v !== value);
      if (selectedFilters[field].length === 0) delete selectedFilters[field];
    } else {
      selectedFilters[field] = [...current, value];
    }
    selectedFilters = { ...selectedFilters };
    doSearch();
  }

  function clearAllFilters() {
    selectedFilters = {};
    doSearch();
  }

  function toggleFacetExpand(field: string) {
    const next = new Set(expandedFacets);
    if (next.has(field)) next.delete(field);
    else next.add(field);
    expandedFacets = next;
  }

  // ─── Mode Toggle ──────────────────────────────────────────────────
  function switchMode(mode: SearchMode) {
    if (searchMode === mode) return;
    searchMode = mode;
    selectedFilters = {};
    facets = [];
    pagination = null;
    currentPage = 1;
    if (searchQuery.trim()) doSearch();
  }

  // ─── Navigate to profile (preserving state) ───────────────────────
  function goToProfile(entityId: string) {
    saveSearchState(true);
    goto(`/profile/${entityId}`);
  }

  // ─── Suggestions ──────────────────────────────────────────────────
  const fuzzySuggestions = ['Juan Dela Cruz', 'PHL-1234', 'Maria Santos', 'Reyes Jr.'];
  const semanticSuggestions = [
    'customers with multiple loan defaults and high outstanding balances',
    'individuals flagged by AMLC or OFAC for money laundering',
    'credit cards cancelled for non-payment in Metro Manila branches',
    'high-risk companies with confirmed fraud and NBI records',
    'diamond or platinum tier clients who got blacklisted',
    'people with both loan default and AML flags',
    'accounts with garnishment orders from Davao or Cebu',
    'repeat offenders with more than 3 negative reasons',
  ];

  // ─── Load stats + restore state on mount ──────────────────────────
  onMount(() => {
    getStats().then(resp => { stats = resp.profile; }).catch(() => {});

    const shouldReSearch = restoreSearchState();
    if (shouldReSearch) {
      doSearch();
    }
  });

  // ─── Drawer tab state ─────────────────────────────────────────────
  const BASE = 'http://localhost:8000/api/negative-list';
  let queryDrawerTab: 'query' | 'api' | 'response' = $state('query');
</script>

<svelte:head>
  <title>MB Negative List Search</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin="anonymous" />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet" />
</svelte:head>

<div class="min-h-screen bg-gradient-to-b from-[#0B1120] to-[#111827] font-sans">

  <!-- ═══════════════════════════════════════════════════════════════ -->
  <!-- ZONE 1: Header + Search + Stats                                -->
  <!-- ═══════════════════════════════════════════════════════════════ -->
  <header class="border-b border-slate-700/50 bg-[#0B1120]/80 backdrop-blur-sm sticky top-0 z-40">
    <!-- Top bar -->
    <div class="max-w-[1600px] mx-auto px-6 py-4">
      <div class="flex items-center justify-between mb-4">
        <div class="flex items-center gap-3">
          <!-- MB Logo Mark -->
          <div class="w-10 h-10 rounded-lg bg-[#1E40AF] flex items-center justify-center font-bold text-white text-lg tracking-tight">
            MB
          </div>
          <div>
            <h1 class="text-lg font-semibold text-white tracking-tight">Negative List Search</h1>
            <p class="text-xs text-slate-500">Meridian Bank -- Risk Management</p>
          </div>
        </div>

        <!-- Mode Toggle -->
        <div class="flex items-center gap-2">
          <button
            class="px-4 py-2 rounded-l-full text-sm font-medium transition-all duration-200 border
              {searchMode === 'fuzzy'
                ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/50 glow-green'
                : 'bg-slate-800 text-slate-400 border-slate-600 hover:bg-slate-700'}"
            onclick={() => switchMode('fuzzy')}
          >
            <span class="inline-block w-2 h-2 rounded-full mr-2 {searchMode === 'fuzzy' ? 'bg-emerald-400' : 'bg-slate-600'}"></span>
            Fuzzy
          </button>
          <button
            class="px-4 py-2 rounded-r-full text-sm font-medium transition-all duration-200 border
              {searchMode === 'semantic'
                ? 'bg-violet-500/20 text-violet-300 border-violet-500/50 glow-violet'
                : 'bg-slate-800 text-slate-400 border-slate-600 hover:bg-slate-700'}"
            onclick={() => switchMode('semantic')}
          >
            <span class="inline-block w-2 h-2 rounded-full mr-2 {searchMode === 'semantic' ? 'bg-violet-400' : 'bg-slate-600'}"></span>
            Semantic
          </button>
        </div>
      </div>

      <!-- Stats bar -->
      <div class="mb-4 grid grid-cols-2 md:grid-cols-4 gap-3">
        <div class="bg-[#1E293B]/60 border border-slate-700/30 rounded-lg px-4 py-2.5">
          <p class="text-[10px] text-slate-500 uppercase tracking-wider">Total Entries</p>
          <p class="text-lg font-semibold text-white">{stats?.total?.toLocaleString() ?? '--'}</p>
        </div>
        <div class="bg-[#1E293B]/60 border border-slate-700/30 rounded-lg px-4 py-2.5">
          <p class="text-[10px] text-slate-500 uppercase tracking-wider">Active</p>
          <p class="text-lg font-semibold text-red-400">{stats?.active?.toLocaleString() ?? '--'}</p>
        </div>
        <div class="bg-[#1E293B]/60 border border-slate-700/30 rounded-lg px-4 py-2.5">
          <p class="text-[10px] text-slate-500 uppercase tracking-wider">Resolved</p>
          <p class="text-lg font-semibold text-emerald-400">{stats?.resolved?.toLocaleString() ?? '--'}</p>
        </div>
        <div class="bg-[#1E293B]/60 border border-slate-700/30 rounded-lg px-4 py-2.5">
          <p class="text-[10px] text-slate-500 uppercase tracking-wider">Total Exposure</p>
          <p class="text-lg font-semibold text-amber-400">{stats?.totalExposure ? compactPhp.format(stats.totalExposure) : '--'}</p>
        </div>
      </div>

      <!-- Search label -->
      <p class="text-xs text-slate-500 mb-2 ml-1">
        {searchMode === 'fuzzy' ? 'Atlas Search -- Fuzzy Match' : 'Atlas Vector Search -- Semantic'}
      </p>

      <!-- Search bar -->
      <div class="relative">
        <div class="relative flex items-center">
          <!-- Search icon -->
          <svg class="absolute left-4 w-5 h-5 text-slate-500 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            bind:value={searchQuery}
            oninput={onSearchInput}
            onkeydown={handleSearchKeydown}
            onfocus={() => { if (acResults.length > 0 && searchMode === 'fuzzy') acVisible = true; }}
            onblur={() => { setTimeout(() => { acVisible = false; }, 200); }}
            placeholder={searchMode === 'fuzzy'
              ? 'Search by name, national ID, TIN, or account number...'
              : 'Describe who you\'re looking for in natural language...'}
            class="w-full pl-12 pr-36 py-3.5 bg-[#1E293B] border border-slate-600/50 rounded-xl text-white placeholder-slate-500 focus:outline-none focus:border-{searchMode === 'fuzzy' ? 'emerald' : 'violet'}-500/70 focus:ring-1 focus:ring-{searchMode === 'fuzzy' ? 'emerald' : 'violet'}-500/30 transition-all text-sm"
          />
          <div class="absolute right-2 flex items-center gap-2">
            <button
              class="text-xs text-slate-500 hover:text-slate-300 px-2 py-1 transition-colors"
              onclick={() => { showFilters = !showFilters; }}
            >
              {showFilters ? 'Hide' : 'Filters'}
              <svg class="inline w-3 h-3 ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
              </svg>
            </button>
            <button
              onclick={() => doSearch()}
              disabled={isSearching || !searchQuery.trim()}
              class="px-5 py-2 bg-[#1E40AF] hover:bg-[#990000] disabled:bg-slate-700 disabled:text-slate-500 text-white text-sm font-medium rounded-lg transition-all duration-200"
            >
              {isSearching ? 'Searching...' : 'Search'}
            </button>
          </div>
        </div>

        <!-- Autocomplete dropdown -->
        {#if acVisible && searchMode === 'fuzzy'}
          <div class="absolute top-full left-0 right-0 mt-1 bg-[#1E293B] border border-slate-600/50 rounded-xl shadow-2xl overflow-hidden z-50 max-h-80 overflow-y-auto">
            {#each acResults as entry}
              <button
                class="w-full text-left px-4 py-3 hover:bg-slate-700/50 transition-colors border-b border-slate-700/30 last:border-b-0"
                onmousedown={() => selectAutoComplete(entry)}
              >
                <div class="flex items-center justify-between">
                  <div>
                    <span class="text-sm text-white font-medium">{entry.fullName}</span>
                    {#if entry.aliases?.length}
                      <span class="text-xs text-slate-500 ml-2">aka {entry.aliases[0]}</span>
                    {/if}
                  </div>
                  <span class="text-xs px-2 py-0.5 rounded-full border {riskColor(entry.riskScore)}">
                    {entry.riskScore?.toFixed(2)}
                  </span>
                </div>
                <div class="flex gap-2 mt-1">
                  {#each (entry.negativeReasons || []).slice(0, 2) as reason}
                    <span class="text-[10px] px-1.5 py-0.5 rounded border {reasonColor(reason.code)}">{reason.code}</span>
                  {/each}
                  <span class="text-[10px] text-slate-500">{entry.entityId}</span>
                </div>
              </button>
            {/each}
          </div>
        {/if}
      </div>

      <!-- Suggestions below search bar -->
      {#if !hasSearched}
        <div class="mt-3 flex flex-wrap gap-2">
          {#if searchMode === 'semantic'}
            <span class="text-[10px] text-violet-400/60 uppercase tracking-wider mr-1 self-center">Try:</span>
            {#each semanticSuggestions as suggestion}
              <button
                class="px-3 py-1.5 bg-violet-500/10 hover:bg-violet-500/20 border border-violet-500/20 hover:border-violet-500/40 rounded-full text-xs text-violet-300/80 hover:text-violet-200 transition-all"
                onclick={() => { searchQuery = suggestion; doSearch(); }}
              >
                {suggestion}
              </button>
            {/each}
          {:else}
            <span class="text-[10px] text-slate-500 uppercase tracking-wider mr-1 self-center">Try:</span>
            {#each fuzzySuggestions as suggestion}
              <button
                class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-700/50 rounded-full text-xs text-slate-400 hover:text-slate-200 transition-all"
                onclick={() => { searchQuery = suggestion; doSearch(); }}
              >
                {suggestion}
              </button>
            {/each}
          {/if}
        </div>
      {/if}

      <!-- Filters row -->
      {#if showFilters}
        <div class="mt-3 flex flex-wrap items-center gap-4 p-3 bg-[#1E293B]/50 rounded-lg border border-slate-700/30">
          <div class="flex flex-col gap-1">
            <label class="text-[10px] text-slate-500 uppercase tracking-wider">Date of Birth</label>
            <input
              type="date"
              bind:value={dobFilter}
              class="px-3 py-1.5 bg-slate-800 border border-slate-600/50 rounded text-xs text-slate-300 focus:outline-none focus:border-slate-500"
            />
          </div>
          <div class="flex flex-col gap-1">
            <label class="text-[10px] text-slate-500 uppercase tracking-wider">National ID</label>
            <input
              type="text"
              bind:value={nationalIdFilter}
              placeholder="e.g. PHL-XXXX"
              class="px-3 py-1.5 bg-slate-800 border border-slate-600/50 rounded text-xs text-slate-300 placeholder-slate-600 focus:outline-none focus:border-slate-500 w-40"
            />
          </div>
          {#if searchMode === 'fuzzy'}
            <div class="flex flex-col gap-1">
              <label class="text-[10px] text-slate-500 uppercase tracking-wider">Max Edit Distance: {maxEdits}</label>
              <input
                type="range"
                min="0"
                max="2"
                bind:value={maxEdits}
                class="w-32 accent-emerald-500"
              />
              <div class="flex justify-between text-[9px] text-slate-600 w-32">
                <span>0</span><span>1</span><span>2</span>
              </div>
            </div>
          {/if}
          <button
            class="text-xs text-slate-500 hover:text-slate-300 underline mt-4"
            onclick={() => { dobFilter = ''; nationalIdFilter = ''; maxEdits = 1; }}
          >
            Clear filters
          </button>
        </div>
      {/if}

    </div>
  </header>

  <!-- ═══════════════════════════════════════════════════════════════ -->
  <!-- ZONE 2: Facets + Results                                        -->
  <!-- ═══════════════════════════════════════════════════════════════ -->
  <main class="max-w-[1600px] mx-auto px-6 py-6">
    {#if searchError}
      <div class="mb-4 p-4 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm">
        {searchError}
      </div>
    {/if}

    {#if !hasSearched && searchResults.length === 0 && !isSearching}
      <!-- Empty state -->
      <div class="flex flex-col items-center justify-center py-24 text-center">
        <div class="w-20 h-20 rounded-full bg-slate-800 flex items-center justify-center mb-6">
          <svg class="w-10 h-10 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        </div>
        <h2 class="text-xl font-semibold text-slate-400 mb-2">Search the Negative List</h2>
        <p class="text-sm text-slate-600 max-w-md">
          {searchMode === 'fuzzy'
            ? 'Enter a name, national ID, TIN, or account number to search the MB negative list database.'
            : 'Describe the type of person or situation you\'re looking for. Semantic search understands meaning, not just keywords.'}
        </p>
      </div>
    {:else}
      <div class="flex gap-6">
        <!-- ── Facet Sidebar (fuzzy mode, togglable) ── -->
        {#if searchMode === 'fuzzy' && facets.length > 0 && showFacetSidebar}
          <aside class="w-64 shrink-0 transition-all">
            <div class="bg-[#1E293B] border border-slate-700/50 rounded-xl overflow-hidden sticky top-[220px]">
              <div class="px-4 py-3 border-b border-slate-700/50 flex items-center justify-between">
                <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-wider">Filters</h3>
                <div class="flex items-center gap-2">
                  {#if activeFilterCount > 0}
                    <button class="text-[10px] text-red-400 hover:text-red-300 transition-colors" onclick={clearAllFilters}>
                      Clear ({activeFilterCount})
                    </button>
                  {/if}
                  <button
                    class="text-slate-500 hover:text-slate-300 transition-colors"
                    onclick={() => { showFacetSidebar = false; }}
                    aria-label="Hide filters"
                  >
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              </div>
              <div class="max-h-[calc(100vh-280px)] overflow-y-auto">
                {#each facets as facet}
                  {@const isExpanded = expandedFacets.has(facet.field) || (selectedFilters[facet.field]?.length ?? 0) > 0}
                  {@const selected = selectedFilters[facet.field] || []}
                  <div class="border-b border-slate-700/30 last:border-b-0">
                    <button
                      class="w-full flex items-center justify-between px-4 py-2.5 text-xs font-medium text-slate-300 hover:bg-slate-700/30 transition-colors"
                      onclick={() => toggleFacetExpand(facet.field)}
                    >
                      <span class="flex items-center gap-2">
                        {facet.label}
                        {#if selected.length > 0}
                          <span class="px-1.5 py-0.5 rounded-full bg-[#1E40AF]/20 text-[9px] text-red-300 font-medium">{selected.length}</span>
                        {/if}
                      </span>
                      <svg class="w-3 h-3 text-slate-600 transition-transform {isExpanded ? 'rotate-180' : ''}" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
                      </svg>
                    </button>
                    {#if isExpanded}
                      <div class="px-4 pb-2.5 space-y-1">
                        {#each facet.buckets.slice(0, 10) as bucket}
                          {@const isChecked = selected.includes(bucket.value)}
                          <label class="flex items-center gap-2 py-0.5 cursor-pointer group">
                            <input
                              type="checkbox"
                              checked={isChecked}
                              onchange={() => toggleFacetValue(facet.field, bucket.value)}
                              class="w-3.5 h-3.5 rounded border-slate-600 bg-slate-800 text-[#1E40AF] focus:ring-0 focus:ring-offset-0 cursor-pointer"
                            />
                            <span class="flex-1 text-[11px] text-slate-400 group-hover:text-slate-200 truncate transition-colors">{bucket.value}</span>
                            <span class="text-[10px] text-slate-600 tabular-nums shrink-0">{bucket.count.toLocaleString()}</span>
                          </label>
                        {/each}
                      </div>
                    {/if}
                  </div>
                {/each}
              </div>
            </div>
          </aside>
        {/if}

        <!-- ── Results Panel ── -->
        <div class="flex-1 min-w-0">
          <!-- Results header -->
          <div class="flex items-center justify-between mb-4">
            <div class="flex items-center gap-3">
              {#if searchMode === 'fuzzy' && facets.length > 0 && !showFacetSidebar}
                <button
                  class="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-700/50 rounded-lg text-xs text-slate-400 hover:text-slate-200 transition-all"
                  onclick={() => { showFacetSidebar = true; }}
                >
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
                  </svg>
                  Filters
                  {#if activeFilterCount > 0}
                    <span class="px-1.5 py-0.5 rounded-full bg-[#1E40AF]/20 text-[9px] text-red-300 font-medium">{activeFilterCount}</span>
                  {/if}
                </button>
              {/if}
              <div>
                {#if pagination}
                  {@const start = (currentPage - 1) * pagination.limit + 1}
                  {@const end = start + pagination.currentPageSize - 1}
                  <span class="text-sm text-slate-400">
                    Showing {start}-{end}
                    {#if pagination.totalCount > 0}
                      <span class="text-slate-600">of ~{pagination.totalCount.toLocaleString()}</span>
                    {/if}
                  </span>
                {:else}
                  <span class="text-sm text-slate-400">
                    {searchResults.length} result{searchResults.length !== 1 ? 's' : ''}
                  </span>
                {/if}
                {#if activeFilterCount > 0}
                  <span class="text-xs text-[#1E40AF] ml-2">({activeFilterCount} filter{activeFilterCount !== 1 ? 's' : ''} active)</span>
                {/if}
              </div>
            </div>
            <button
              class="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-700/50 rounded-lg text-xs text-slate-400 hover:text-slate-200 transition-all"
              onclick={() => { queryDrawerTab = 'query'; showQueryDrawer = true; }}
            >
              <span class="font-mono">&#123; &#125;</span> Show Query
            </button>
          </div>

          <!-- Results table -->
          <div class="bg-[#1E293B] border border-slate-700/50 rounded-xl overflow-hidden">
            <table class="w-full">
              <thead>
                <tr class="border-b border-slate-700/50">
                  <th class="text-left text-[10px] text-slate-500 uppercase tracking-wider font-medium px-5 py-3 w-12">Risk</th>
                  <th class="text-left text-[10px] text-slate-500 uppercase tracking-wider font-medium px-3 py-3">Name</th>
                  <th class="text-left text-[10px] text-slate-500 uppercase tracking-wider font-medium px-3 py-3 w-36">Match</th>
                  <th class="text-left text-[10px] text-slate-500 uppercase tracking-wider font-medium px-3 py-3">Reasons</th>
                  <th class="text-left text-[10px] text-slate-500 uppercase tracking-wider font-medium px-3 py-3 w-28">Sources</th>
                  <th class="text-right text-[10px] text-slate-500 uppercase tracking-wider font-medium px-3 py-3 w-24">Type</th>
                  <th class="text-right text-[10px] text-slate-500 uppercase tracking-wider font-medium px-5 py-3 w-36">Entity ID</th>
                  <th class="px-3 py-3 w-6"></th>
                </tr>
              </thead>
              <tbody>
                {#if isSearching}
                  {#each Array(4) as _}
                    <tr class="border-b border-slate-700/20">
                      <td class="px-5 py-3"><div class="w-9 h-9 bg-slate-700/50 rounded-full animate-pulse"></div></td>
                      <td class="px-3 py-3"><div class="h-4 bg-slate-700/50 rounded w-36 animate-pulse"></div></td>
                      <td class="px-3 py-3"><div class="h-3 bg-slate-700/50 rounded w-24 animate-pulse"></div></td>
                      <td class="px-3 py-3"><div class="h-5 bg-slate-700/50 rounded w-20 animate-pulse"></div></td>
                      <td class="px-3 py-3"><div class="h-4 bg-slate-700/50 rounded w-16 animate-pulse"></div></td>
                      <td class="px-3 py-3"><div class="h-4 bg-slate-700/50 rounded w-14 animate-pulse ml-auto"></div></td>
                      <td class="px-5 py-3"><div class="h-4 bg-slate-700/50 rounded w-28 animate-pulse ml-auto"></div></td>
                      <td class="px-3 py-3"></td>
                    </tr>
                  {/each}
                {/if}
                {#each searchResults as entry (entry._id)}
                  {@const matchPct = normalizeScore(entry.score, searchMode)}
                  <tr
                    class="border-b border-slate-700/20 last:border-b-0 hover:bg-[#263548] transition-colors cursor-pointer group"
                    onclick={() => goToProfile(entry.entityId)}
                  >
                    <td class="px-5 py-3">
                      <div class="w-9 h-9 rounded-full border-2 flex items-center justify-center text-xs font-bold {riskColor(entry.riskScore)}">
                        {entry.riskScore?.toFixed(1)}
                      </div>
                    </td>
                    <td class="px-3 py-3 max-w-[220px]">
                      <p class="text-sm font-semibold text-white truncate group-hover:text-slate-50">{entry.fullName}</p>
                      {#if entry.aliases?.length}
                        <p class="text-[11px] text-slate-500 truncate">aka {entry.aliases[0]}</p>
                      {/if}
                    </td>
                    <td class="px-3 py-3">
                      <div class="flex items-center gap-2">
                        <div class="flex-1 h-1.5 bg-slate-700/50 rounded-full overflow-hidden">
                          <div class="h-full rounded-full {searchMode === 'fuzzy' ? 'bg-emerald-500' : 'bg-violet-500'}" style="width: {matchPct}%"></div>
                        </div>
                        <span class="text-xs font-medium {searchMode === 'fuzzy' ? 'text-emerald-400' : 'text-violet-400'} tabular-nums w-9 text-right">{matchPct}%</span>
                      </div>
                    </td>
                    <td class="px-3 py-3">
                      <div class="flex flex-wrap gap-1">
                        {#each (entry.negativeReasons || []).slice(0, 3) as reason}
                          <span class="text-[10px] px-2 py-0.5 rounded-full border font-medium {reasonColor(reason.code)}">{reason.code}</span>
                        {/each}
                        {#if (entry.negativeReasons?.length || 0) > 3}
                          <span class="text-[10px] px-2 py-0.5 rounded-full border border-slate-600 text-slate-500">+{entry.negativeReasons.length - 3}</span>
                        {/if}
                      </div>
                    </td>
                    <td class="px-3 py-3">
                      <div class="flex flex-wrap gap-1">
                        {#each (entry.watchlistSources || []).slice(0, 2) as ws}
                          <span class="text-[9px] px-1.5 py-0.5 rounded bg-slate-700/50 text-slate-500">{ws.source}</span>
                        {/each}
                      </div>
                    </td>
                    <td class="px-3 py-3 text-right">
                      <span class="text-[10px] px-2 py-0.5 rounded bg-slate-700/30 text-slate-500">{entry.entityType}</span>
                    </td>
                    <td class="px-5 py-3 text-right">
                      <span class="text-[10px] text-slate-600 font-mono">{entry.entityId}</span>
                    </td>
                    <td class="px-3 py-3">
                      <svg class="w-4 h-4 text-slate-600 group-hover:text-slate-400 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
                      </svg>
                    </td>
                  </tr>
                {/each}
                {#if !isSearching && searchResults.length === 0 && hasSearched}
                  <tr>
                    <td colspan="8" class="px-5 py-12 text-center">
                      <p class="text-sm text-slate-500">No results found for "{searchQuery}"</p>
                      {#if activeFilterCount > 0}
                        <button class="mt-2 text-xs text-[#1E40AF] hover:text-red-300 underline" onclick={clearAllFilters}>Clear filters and try again</button>
                      {/if}
                    </td>
                  </tr>
                {/if}
              </tbody>
            </table>
          </div>

          <!-- Pagination -->
          {#if pagination && (pagination.totalCount > 0 || searchResults.length > 0)}
            <div class="mt-4 flex items-center justify-between">
              <div class="text-xs text-slate-500">
                Page {currentPage}
                {#if pagination.totalCount > 0}
                  of ~{Math.ceil(pagination.totalCount / pagination.limit).toLocaleString()}
                {/if}
              </div>
              <div class="flex items-center gap-2">
                <button
                  disabled={currentPage <= 1 || isSearching}
                  onclick={handlePrevPage}
                  class="flex items-center gap-1.5 px-4 py-2 bg-slate-800 hover:bg-slate-700 disabled:bg-slate-800/50 disabled:text-slate-600 border border-slate-700/50 rounded-lg text-xs text-slate-300 hover:text-white transition-all disabled:cursor-not-allowed"
                >
                  <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" /></svg>
                  Previous
                </button>
                <button
                  disabled={!pagination.hasMore || isSearching}
                  onclick={handleNextPage}
                  class="flex items-center gap-1.5 px-4 py-2 bg-slate-800 hover:bg-slate-700 disabled:bg-slate-800/50 disabled:text-slate-600 border border-slate-700/50 rounded-lg text-xs text-slate-300 hover:text-white transition-all disabled:cursor-not-allowed"
                >
                  Next
                  <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" /></svg>
                </button>
              </div>
            </div>
          {/if}
        </div>
      </div>
    {/if}
  </main>

  <!-- ═══════════════════════════════════════════════════════════════ -->
  <!-- QUERY DRAWER                                                    -->
  <!-- ═══════════════════════════════════════════════════════════════ -->
  {#if showQueryDrawer}
    <div class="drawer-overlay" onclick={() => { showQueryDrawer = false; }} role="presentation"></div>
    <div class="drawer-panel">
      <!-- Header -->
      <div class="sticky top-0 bg-gradient-to-r from-[#0F172A] to-[#1E293B] border-b border-slate-700/50 px-5 py-4 flex items-center justify-between z-10">
        <div class="flex items-center gap-3">
          <div class="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
            <svg class="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" /></svg>
          </div>
          <div>
            <h3 class="text-sm font-semibold text-white">Query Inspector</h3>
            <p class="text-[10px] text-slate-500">MongoDB Atlas Search</p>
          </div>
        </div>
        <button
          class="w-8 h-8 rounded-lg bg-slate-800/80 hover:bg-slate-700 flex items-center justify-center text-slate-400 hover:text-white transition-all hover:rotate-90 duration-200"
          onclick={() => { showQueryDrawer = false; }}
          aria-label="Close drawer"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" /></svg>
        </button>
      </div>

      <!-- Tabs -->
      <div class="flex bg-[#0F172A]/50 border-b border-slate-700/50">
        {#each [
          { key: 'query', label: 'MongoDB Query', icon: '&#9671;' },
          { key: 'api', label: 'API Call', icon: '&#8594;' },
          { key: 'response', label: 'Response', icon: '&#123;&#125;' }
        ] as tab}
          <button
            class="flex-1 px-3 py-2.5 text-[11px] font-medium transition-all border-b-2 {
              queryDrawerTab === tab.key
                ? 'text-emerald-400 border-emerald-400 bg-emerald-400/5'
                : 'text-slate-500 border-transparent hover:text-slate-300 hover:bg-slate-800/30'
            }"
            onclick={() => { queryDrawerTab = tab.key as typeof queryDrawerTab; }}
          >
            <span class="mr-1">{@html tab.icon}</span> {tab.label}
          </button>
        {/each}
      </div>

      <div class="flex-1 overflow-y-auto">

        <!-- ═══ TAB: MongoDB Query ═══ -->
        {#if queryDrawerTab === 'query'}
          <div class="p-5">
            {#if searchMeta?.pipeline || searchMeta?.query}
              <!-- Pill badges -->
              <div class="flex items-center gap-2 mb-4">
                <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  <span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                  {searchMeta?.searchMode === 'fuzzy' ? 'Atlas Search' : 'Vector Search'}
                </span>
                {#if searchMeta?.index}
                  <span class="inline-flex items-center px-2.5 py-1 rounded-full text-[10px] font-medium bg-slate-700/50 text-slate-400 border border-slate-600/30">
                    index: {searchMeta.index}
                  </span>
                {/if}
                {#if searchMeta?.resultsCount !== undefined}
                  <span class="inline-flex items-center px-2.5 py-1 rounded-full text-[10px] font-medium bg-slate-700/50 text-slate-400 border border-slate-600/30">
                    {searchMeta.resultsCount} results
                  </span>
                {/if}
              </div>

              <!-- db.collection header -->
              <div class="flex items-center justify-between mb-2">
                <div class="flex items-center gap-2">
                  <span class="text-[10px] text-slate-500 uppercase tracking-widest font-semibold">Aggregation Pipeline</span>
                </div>
                <button
                  class="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] text-slate-500 hover:text-emerald-400 hover:bg-emerald-400/5 transition-all"
                  onclick={() => {
                    const pipelineData = searchMeta?.pipeline || searchMeta?.query || {};
                    const formatted = `db.getCollection("negative_list").aggregate(\n${JSON.stringify(pipelineData, null, 2)}\n)`;
                    copyToClipboard(formatted);
                  }}
                >
                  <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>
                  Copy
                </button>
              </div>

              <div class="relative rounded-xl overflow-hidden border border-slate-700/40 bg-[#0D1117]">
                <!-- Top bar mimicking a code editor -->
                <div class="flex items-center gap-2 px-4 py-2.5 bg-[#161B22] border-b border-slate-700/40">
                  <div class="flex gap-1.5">
                    <span class="w-2.5 h-2.5 rounded-full bg-red-500/60"></span>
                    <span class="w-2.5 h-2.5 rounded-full bg-yellow-500/60"></span>
                    <span class="w-2.5 h-2.5 rounded-full bg-green-500/60"></span>
                  </div>
                  <span class="text-[10px] text-slate-500 font-mono ml-2">mongosh</span>
                </div>
                <pre class="p-4 text-xs leading-relaxed overflow-x-auto overflow-y-auto max-h-[60vh] font-mono"><code><span class="text-slate-500">// Atlas Search — {searchMeta?.searchMode === 'fuzzy' ? 'Fuzzy matching with compound operators' : 'Vector similarity via Voyage AI embeddings'}</span>
<span class="text-cyan-400">db</span>.<span class="text-emerald-400">getCollection</span>(<span class="text-amber-300">"negative_list"</span>).<span class="text-emerald-400">aggregate</span>(
{@html syntaxHighlightJson(searchMeta.pipeline || searchMeta.query)}
)</code></pre>
              </div>

              <p class="text-[10px] text-slate-600 mt-3 flex items-center gap-1.5">
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
                {searchMeta?.searchMode === 'fuzzy'
                  ? 'Uses $search with compound operators and fuzzy text matching.'
                  : 'Uses $vectorSearch for semantic similarity matching.'}
                Paste directly in MongoDB Compass or mongosh.
              </p>
            {:else}
              <div class="flex flex-col items-center justify-center py-16 text-center">
                <div class="w-14 h-14 rounded-2xl bg-slate-800/50 border border-slate-700/30 flex items-center justify-center mb-4">
                  <svg class="w-6 h-6 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
                </div>
                <p class="text-sm text-slate-500 mb-1">No query yet</p>
                <p class="text-[11px] text-slate-600">Run a search to see the MongoDB aggregation pipeline.</p>
              </div>
            {/if}
          </div>

        <!-- ═══ TAB: API Call ═══ -->
        {:else if queryDrawerTab === 'api'}
          <div class="p-5">
            <div class="flex items-center justify-between mb-4">
              <div class="flex items-center gap-2">
                <span class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold tracking-wide {
                  searchMode === 'fuzzy' ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' : 'bg-blue-500/10 text-blue-400 border border-blue-500/20'
                }">
                  {searchMode === 'fuzzy' ? 'POST' : 'GET'}
                </span>
                <span class="text-xs text-slate-400 font-mono">/api/negative-list/search</span>
              </div>
              <button
                class="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] text-slate-500 hover:text-emerald-400 hover:bg-emerald-400/5 transition-all"
                onclick={() => {
                  if (searchMode === 'fuzzy') {
                    copyToClipboard(JSON.stringify({ query: searchQuery, mode: searchMode, max_edits: maxEdits, limit: 20, use_facets: true, filters: Object.keys(selectedFilters).length > 0 ? selectedFilters : undefined }, null, 2));
                  } else {
                    copyToClipboard(`GET /api/negative-list/search?q=${encodeURIComponent(searchQuery)}&mode=semantic&limit=20`);
                  }
                }}
              >
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>
                Copy
              </button>
            </div>

            {#if searchMode === 'fuzzy'}
              <div class="relative rounded-xl overflow-hidden border border-slate-700/40 bg-[#0D1117]">
                <div class="flex items-center gap-2 px-4 py-2.5 bg-[#161B22] border-b border-slate-700/40">
                  <div class="flex gap-1.5">
                    <span class="w-2.5 h-2.5 rounded-full bg-red-500/60"></span>
                    <span class="w-2.5 h-2.5 rounded-full bg-yellow-500/60"></span>
                    <span class="w-2.5 h-2.5 rounded-full bg-green-500/60"></span>
                  </div>
                  <span class="text-[10px] text-slate-500 font-mono ml-2">request.json</span>
                </div>
                <pre class="p-4 text-xs leading-relaxed overflow-x-auto overflow-y-auto max-h-[50vh] font-mono"><code><span class="text-slate-500">// POST /api/negative-list/search</span>
{@html syntaxHighlightJson({
  query: searchQuery,
  mode: 'fuzzy',
  max_edits: maxEdits,
  limit: 20,
  use_facets: true,
  filters: Object.keys(selectedFilters).length > 0 ? selectedFilters : undefined,
})}</code></pre>
              </div>
            {:else}
              <div class="relative rounded-xl overflow-hidden border border-slate-700/40 bg-[#0D1117]">
                <div class="flex items-center gap-2 px-4 py-2.5 bg-[#161B22] border-b border-slate-700/40">
                  <div class="flex gap-1.5">
                    <span class="w-2.5 h-2.5 rounded-full bg-red-500/60"></span>
                    <span class="w-2.5 h-2.5 rounded-full bg-yellow-500/60"></span>
                    <span class="w-2.5 h-2.5 rounded-full bg-green-500/60"></span>
                  </div>
                  <span class="text-[10px] text-slate-500 font-mono ml-2">request</span>
                </div>
                <pre class="p-4 text-xs leading-relaxed overflow-x-auto font-mono"><code><span class="text-cyan-400">GET</span> <span class="text-emerald-400">/api/negative-list/search</span>?<span class="text-amber-300">q</span>={searchQuery}&<span class="text-amber-300">mode</span>=semantic&<span class="text-amber-300">limit</span>=20</code></pre>
              </div>
            {/if}

            <!-- Curl example -->
            <div class="mt-5">
              <div class="flex items-center justify-between mb-2">
                <span class="text-[10px] text-slate-500 uppercase tracking-widest font-semibold">cURL</span>
                <button
                  class="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] text-slate-500 hover:text-emerald-400 hover:bg-emerald-400/5 transition-all"
                  onclick={() => {
                    if (searchMode === 'fuzzy') {
                      const body = JSON.stringify({ query: searchQuery, mode: 'fuzzy', max_edits: maxEdits, limit: 20, use_facets: true, filters: Object.keys(selectedFilters).length > 0 ? selectedFilters : undefined });
                      copyToClipboard(`curl -X POST http://localhost:8000/api/negative-list/search \\\n  -H "Content-Type: application/json" \\\n  -d '${body}'`);
                    } else {
                      copyToClipboard(`curl "http://localhost:8000/api/negative-list/search?q=${encodeURIComponent(searchQuery)}&mode=semantic&limit=20"`);
                    }
                  }}
                >
                  <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>
                  Copy
                </button>
              </div>
              <div class="relative rounded-xl overflow-hidden border border-slate-700/40 bg-[#0D1117]">
                <pre class="p-4 text-[11px] leading-relaxed overflow-x-auto font-mono text-slate-400"><code>{#if searchMode === 'fuzzy'}curl -X POST http://localhost:8000/api/negative-list/search \
  -H <span class="text-amber-300">"Content-Type: application/json"</span> \
  -d <span class="text-emerald-400">'{JSON.stringify({ query: searchQuery, mode: 'fuzzy', max_edits: maxEdits, limit: 20 })}'</span>{:else}curl <span class="text-emerald-400">"http://localhost:8000/api/negative-list/search?q={encodeURIComponent(searchQuery)}&mode=semantic&limit=20"</span>{/if}</code></pre>
              </div>
            </div>
          </div>

        <!-- ═══ TAB: Response ═══ -->
        {:else if queryDrawerTab === 'response'}
          <div class="p-5">
            {#if searchMeta}
              <!-- Summary badges -->
              <div class="flex items-center gap-2 mb-4 flex-wrap">
                <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  {searchMeta.resultsCount ?? 0} results
                </span>
                {#if pagination}
                  <span class="inline-flex items-center px-2.5 py-1 rounded-full text-[10px] font-medium bg-slate-700/50 text-slate-400 border border-slate-600/30">
                    page {currentPage}
                  </span>
                {/if}
                {#if facets.length > 0}
                  <span class="inline-flex items-center px-2.5 py-1 rounded-full text-[10px] font-medium bg-slate-700/50 text-slate-400 border border-slate-600/30">
                    {facets.length} facets
                  </span>
                {/if}
              </div>
            {/if}

            <div class="flex items-center justify-between mb-2">
              <span class="text-[10px] text-slate-500 uppercase tracking-widest font-semibold">Full JSON Response</span>
              <button
                class="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] text-slate-500 hover:text-emerald-400 hover:bg-emerald-400/5 transition-all"
                onclick={() => copyToClipboard(JSON.stringify({ _meta: searchMeta, results: searchResults, pagination, facets }, null, 2))}
              >
                <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>
                Copy
              </button>
            </div>
            <div class="relative rounded-xl overflow-hidden border border-slate-700/40 bg-[#0D1117]">
              <div class="flex items-center gap-2 px-4 py-2.5 bg-[#161B22] border-b border-slate-700/40">
                <div class="flex gap-1.5">
                  <span class="w-2.5 h-2.5 rounded-full bg-red-500/60"></span>
                  <span class="w-2.5 h-2.5 rounded-full bg-yellow-500/60"></span>
                  <span class="w-2.5 h-2.5 rounded-full bg-green-500/60"></span>
                </div>
                <span class="text-[10px] text-slate-500 font-mono ml-2">response.json</span>
              </div>
              <pre class="p-4 text-xs leading-relaxed overflow-x-auto overflow-y-auto max-h-[65vh] font-mono"><code>{@html syntaxHighlightJson({ _meta: searchMeta, results: searchResults, pagination, facets })}</code></pre>
            </div>
          </div>
        {/if}

      </div>
    </div>
  {/if}


</div>
