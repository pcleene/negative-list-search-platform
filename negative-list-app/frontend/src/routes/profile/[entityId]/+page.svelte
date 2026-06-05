<script lang="ts">
  import { page } from '$app/stores';
  import {
    getProfile,
    type NegativeEntry,
    type ApiMeta
  } from '$lib/api';

  let profile: NegativeEntry | null = $state(null);
  let profileMeta: ApiMeta | null = $state(null);
  let loading = $state(true);
  let error = $state('');

  let showDocDrawer = $state(false);
  let docDrawerTab: 'query' | 'api' | 'document' | 'response' = $state('query');

  let revealedFields: Set<string> = $state(new Set());

  const BASE = 'http://localhost:8000/api/negative-list';

  const phpFormat = new Intl.NumberFormat('en-PH', {
    style: 'currency', currency: 'PHP', minimumFractionDigits: 0, maximumFractionDigits: 0
  });

  function riskColor(score: number): string {
    if (score > 0.7) return 'text-red-400 bg-red-500/20 border-red-500/50';
    if (score > 0.4) return 'text-amber-400 bg-amber-500/20 border-amber-500/50';
    return 'text-emerald-400 bg-emerald-500/20 border-emerald-500/50';
  }

  function riskGaugeColor(score: number): string {
    if (score > 0.7) return '#EF4444';
    if (score > 0.4) return '#F59E0B';
    return '#10B981';
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

  function tierColor(tier: string): string {
    const t = tier?.toLowerCase();
    if (t === 'platinum') return 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40';
    if (t === 'gold') return 'bg-yellow-500/20 text-yellow-300 border-yellow-500/40';
    if (t === 'silver') return 'bg-slate-400/20 text-slate-300 border-slate-400/40';
    return 'bg-slate-500/20 text-slate-300 border-slate-500/40';
  }

  function maskValue(value: string, fieldKey: string): string {
    if (!value) return '--';
    if (revealedFields.has(fieldKey)) return value;
    if (value.length <= 4) return '****';
    return value.slice(0, 2) + '*'.repeat(value.length - 4) + value.slice(-2);
  }

  function toggleReveal(fieldKey: string) {
    const next = new Set(revealedFields);
    if (next.has(fieldKey)) next.delete(fieldKey);
    else next.add(fieldKey);
    revealedFields = next;
  }

  function formatDate(iso: string): string {
    if (!iso) return '--';
    try {
      return new Date(iso).toLocaleDateString('en-PH', {
        year: 'numeric', month: 'short', day: 'numeric'
      });
    } catch { return iso; }
  }

  function formatDateTime(iso: string): string {
    if (!iso) return '--';
    try {
      return new Date(iso).toLocaleString('en-PH', {
        year: 'numeric', month: 'short', day: 'numeric',
        hour: '2-digit', minute: '2-digit'
      });
    } catch { return iso; }
  }

  function calcTotalExposure(entry: NegativeEntry): number {
    let total = 0;
    entry.accounts?.forEach(a => { total += a.outstandingBalance || 0; });
    entry.loans?.forEach(l => { total += l.outstandingBalance || 0; });
    return total;
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

  $effect(() => {
    const entityId = $page.params.entityId;
    if (!entityId) return;
    loading = true;
    error = '';
    getProfile(entityId).then(resp => {
      profile = resp.profile;
      profileMeta = resp._meta;
    }).catch(err => {
      error = err instanceof Error ? err.message : 'Failed to load profile';
    }).finally(() => {
      loading = false;
    });
  });
</script>

<svelte:head>
  <title>{profile ? profile.fullName + ' — ' : ''}MB Negative List</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin="anonymous" />
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet" />
</svelte:head>

<div class="min-h-screen bg-gradient-to-b from-[#0B1120] to-[#111827] font-sans">

  <!-- Top bar -->
  <header class="border-b border-slate-700/50 bg-[#0B1120]/80 backdrop-blur-sm sticky top-0 z-40">
    <div class="max-w-[1200px] mx-auto px-6 py-4 flex items-center justify-between">
      <div class="flex items-center gap-3">
        <a href="/" class="flex items-center gap-3 hover:opacity-90 transition-opacity">
          <div class="w-10 h-10 rounded-lg bg-[#1E40AF] flex items-center justify-center font-bold text-white text-lg tracking-tight">
            MB
          </div>
          <div>
            <h1 class="text-lg font-semibold text-white tracking-tight">Negative List Search</h1>
            <p class="text-xs text-slate-500">Meridian Bank — Risk Management</p>
          </div>
        </a>
      </div>
      <button
        onclick={() => history.back()}
        class="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700/50 rounded-lg text-sm text-slate-300 hover:text-white transition-all"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
        </svg>
        Back to Search
      </button>
    </div>
  </header>

  <main class="max-w-[1200px] mx-auto px-6 py-6">

    {#if loading}
      <div class="space-y-4">
        <div class="bg-[#1E293B] border border-slate-700/50 rounded-xl p-8 animate-pulse">
          <div class="h-8 bg-slate-700 rounded w-1/3 mb-4"></div>
          <div class="h-4 bg-slate-700/50 rounded w-1/2 mb-3"></div>
          <div class="h-4 bg-slate-700/50 rounded w-2/3 mb-3"></div>
          <div class="h-32 bg-slate-700/30 rounded mt-6"></div>
        </div>
      </div>

    {:else if error}
      <div class="p-6 bg-red-500/10 border border-red-500/30 rounded-xl text-center">
        <p class="text-red-400 mb-3">{error}</p>
        <button onclick={() => history.back()} class="text-sm text-slate-400 hover:text-white underline">Back to search</button>
      </div>

    {:else if profile}
      {@const exposure = calcTotalExposure(profile)}
      <div class="space-y-4">

        <!-- Profile Header -->
        <div class="bg-[#1E293B] border border-slate-700/50 rounded-xl p-6">
          <div class="flex items-start justify-between">
            <div class="flex-1">
              <div class="flex items-center gap-3 mb-1">
                <h2 class="text-2xl font-bold text-white">{profile.fullName}</h2>
                <span class="text-[10px] px-2 py-0.5 rounded-full border {profile.isActive ? 'bg-red-500/20 text-red-300 border-red-500/40' : 'bg-slate-600/20 text-slate-400 border-slate-600/40'}">
                  {profile.isActive ? 'ACTIVE' : 'INACTIVE'}
                </span>
                <span class="text-[10px] px-2 py-0.5 rounded bg-slate-700/30 text-slate-400">
                  {profile.entityType}
                </span>
              </div>
              <p class="text-xs text-slate-500">
                Added {formatDate(profile.createdAt)} | Updated {formatDate(profile.updatedAt)} | Source: {profile.sourceSystem}
              </p>
              {#if profile.aliases?.length}
                <p class="text-xs text-slate-600 mt-1">
                  Aliases: {profile.aliases.join(', ')}
                </p>
              {/if}
            </div>

            <!-- Risk Gauge -->
            <div class="shrink-0 flex flex-col items-center">
              <svg width="100" height="62" viewBox="0 0 100 60">
                <path d="M 10 55 A 40 40 0 0 1 90 55" fill="none" stroke="#334155" stroke-width="6" stroke-linecap="round" />
                <path d="M 10 55 A 40 40 0 0 1 90 55" fill="none" stroke={riskGaugeColor(profile.riskScore)} stroke-width="6" stroke-linecap="round"
                  stroke-dasharray="{125.6 * profile.riskScore} {125.6}" style="transition: stroke-dasharray 1s ease-out;" />
                <text x="50" y="48" text-anchor="middle" fill={riskGaugeColor(profile.riskScore)} font-size="18" font-weight="bold">
                  {profile.riskScore?.toFixed(2)}
                </text>
                <text x="50" y="58" text-anchor="middle" fill="#64748B" font-size="6">RISK SCORE</text>
              </svg>
            </div>
          </div>

          <!-- Risk Tags + Show Document -->
          <div class="flex items-center justify-between mt-4 pt-4 border-t border-slate-700/30">
            <div class="flex flex-wrap gap-1.5">
              {#each profile.riskTags || [] as tag}
                <span class="text-[10px] px-2 py-0.5 rounded-full bg-[#1E40AF]/15 text-red-300 border border-[#1E40AF]/30 font-medium">
                  {tag}
                </span>
              {/each}
            </div>
            <button
              class="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-700/50 rounded-lg text-xs text-slate-400 hover:text-slate-200 transition-all"
              onclick={() => { docDrawerTab = 'query'; showDocDrawer = true; }}
            >
              <span class="font-mono">&#123; &#125;</span> Show Document
            </button>
          </div>
        </div>

        <!-- Quick Stats Row -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div class="bg-[#1E293B]/60 border border-slate-700/30 rounded-lg px-4 py-3">
            <p class="text-[10px] text-slate-500 uppercase tracking-wider">Total Exposure</p>
            <p class="text-lg font-semibold text-red-400">{phpFormat.format(exposure)}</p>
          </div>
          <div class="bg-[#1E293B]/60 border border-slate-700/30 rounded-lg px-4 py-3">
            <p class="text-[10px] text-slate-500 uppercase tracking-wider">Negative Reasons</p>
            <p class="text-lg font-semibold text-amber-400">{profile.negativeReasons?.length ?? 0}</p>
          </div>
          <div class="bg-[#1E293B]/60 border border-slate-700/30 rounded-lg px-4 py-3">
            <p class="text-[10px] text-slate-500 uppercase tracking-wider">Accounts</p>
            <p class="text-lg font-semibold text-cyan-400">{profile.accounts?.length ?? 0}</p>
          </div>
          <div class="bg-[#1E293B]/60 border border-slate-700/30 rounded-lg px-4 py-3">
            <p class="text-[10px] text-slate-500 uppercase tracking-wider">Loans</p>
            <p class="text-lg font-semibold text-violet-400">{profile.loans?.length ?? 0}</p>
          </div>
        </div>

        <!-- Two-column layout for Identity + Banking -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">

          <!-- Identity & Contact -->
          <div class="bg-[#1E293B] border border-slate-700/50 rounded-xl p-5">
            <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Identity & Contact</h3>
            <div class="grid grid-cols-2 gap-x-6 gap-y-3">
              {#each [
                { label: 'National ID', value: profile.identifiers?.nationalId, key: 'nid' },
                { label: 'TIN', value: profile.identifiers?.tin, key: 'tin' },
                { label: 'SSS No.', value: profile.identifiers?.sssNo, key: 'sss' },
                { label: 'Passport', value: profile.identifiers?.passportNo, key: 'passport' },
                { label: "Driver's License", value: profile.identifiers?.driversLicense, key: 'dl' },
                { label: 'GSIS No.', value: profile.identifiers?.gsisNo, key: 'gsis' }
              ] as field}
                <div>
                  <p class="text-[10px] text-slate-600 uppercase tracking-wider">{field.label}</p>
                  <button
                    class="text-sm text-slate-300 font-mono hover:text-white transition-colors flex items-center gap-1 group"
                    onclick={() => toggleReveal(field.key)}
                  >
                    {maskValue(field.value || '', field.key)}
                    <svg class="w-3 h-3 text-slate-600 group-hover:text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      {#if revealedFields.has(field.key)}
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" />
                      {:else}
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                      {/if}
                    </svg>
                  </button>
                </div>
              {/each}
            </div>

            <div class="grid grid-cols-2 gap-x-6 gap-y-3 mt-4 pt-3 border-t border-slate-700/30">
              <div>
                <p class="text-[10px] text-slate-600 uppercase tracking-wider">Phone</p>
                <p class="text-sm text-slate-300">{profile.phone || '--'}</p>
              </div>
              <div>
                <p class="text-[10px] text-slate-600 uppercase tracking-wider">Email</p>
                <p class="text-sm text-slate-300 truncate">{profile.email || '--'}</p>
              </div>
              <div>
                <p class="text-[10px] text-slate-600 uppercase tracking-wider">Nationality</p>
                <p class="text-sm text-slate-300">{profile.nationality || '--'}</p>
              </div>
              <div>
                <p class="text-[10px] text-slate-600 uppercase tracking-wider">DOB / Gender</p>
                <p class="text-sm text-slate-300">{formatDate(profile.dateOfBirth)} / {profile.gender}</p>
              </div>
            </div>
          </div>

          <!-- Banking Relationship -->
          {#if profile.relationship}
            <div class="bg-[#1E293B] border border-slate-700/50 rounded-xl p-5">
              <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Banking Relationship</h3>
              <div class="grid grid-cols-2 gap-x-6 gap-y-3">
                <div>
                  <p class="text-[10px] text-slate-600 uppercase tracking-wider">Customer ID</p>
                  <p class="text-sm text-slate-300 font-mono">{profile.relationship.customerId}</p>
                </div>
                <div>
                  <p class="text-[10px] text-slate-600 uppercase tracking-wider">Since</p>
                  <p class="text-sm text-slate-300">{formatDate(profile.relationship.since)}</p>
                </div>
                <div>
                  <p class="text-[10px] text-slate-600 uppercase tracking-wider">Tier</p>
                  <span class="text-xs px-2 py-0.5 rounded-full border {tierColor(profile.relationship.tier)}">
                    {profile.relationship.tier}
                  </span>
                </div>
                <div>
                  <p class="text-[10px] text-slate-600 uppercase tracking-wider">Segment</p>
                  <p class="text-sm text-slate-300">{profile.relationship.segment}</p>
                </div>
                <div>
                  <p class="text-[10px] text-slate-600 uppercase tracking-wider">Branch</p>
                  <p class="text-sm text-slate-300">{profile.relationship.branch}</p>
                </div>
                <div>
                  <p class="text-[10px] text-slate-600 uppercase tracking-wider">RM</p>
                  <p class="text-sm text-slate-300">{profile.relationship.relationshipManager}</p>
                </div>
                <div>
                  <p class="text-[10px] text-slate-600 uppercase tracking-wider">Status</p>
                  <p class="text-sm">
                    <span class="text-slate-500 line-through">{profile.relationship.previousStatus}</span>
                    <span class="text-slate-400 mx-1">→</span>
                    <span class="text-red-400 font-medium">{profile.relationship.status}</span>
                  </p>
                </div>
                {#if profile.relationship.blacklistedAt}
                  <div>
                    <p class="text-[10px] text-slate-600 uppercase tracking-wider">Blacklisted At</p>
                    <p class="text-sm text-red-400">{formatDate(profile.relationship.blacklistedAt)}</p>
                  </div>
                {/if}
              </div>

              {#if profile.kyc}
                <div class="mt-4 pt-3 border-t border-slate-700/30">
                  <p class="text-[10px] text-slate-500 uppercase tracking-wider mb-2">KYC Details</p>
                  <div class="grid grid-cols-2 gap-x-6 gap-y-2">
                    <div>
                      <p class="text-[10px] text-slate-600">Level</p>
                      <p class="text-xs text-slate-300">{profile.kyc.level}</p>
                    </div>
                    <div>
                      <p class="text-[10px] text-slate-600">Risk Rating</p>
                      <p class="text-xs text-slate-300">{profile.kyc.riskRating}</p>
                    </div>
                    <div>
                      <p class="text-[10px] text-slate-600">PEP Status</p>
                      <p class="text-xs {profile.kyc.pepStatus ? 'text-amber-400' : 'text-slate-500'}">
                        {profile.kyc.pepStatus ? 'Yes' : 'No'}
                      </p>
                    </div>
                    <div>
                      <p class="text-[10px] text-slate-600">FATCA</p>
                      <p class="text-xs {profile.kyc.fatcaReportable ? 'text-amber-400' : 'text-slate-500'}">
                        {profile.kyc.fatcaReportable ? 'Reportable' : 'No'}
                      </p>
                    </div>
                  </div>
                </div>
              {/if}
            </div>
          {/if}
        </div>

        <!-- Accounts -->
        {#if profile.accounts?.length}
          <div class="bg-[#1E293B] border border-slate-700/50 rounded-xl p-5">
            <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
              Accounts <span class="text-slate-600 font-normal">({profile.accounts.length})</span>
            </h3>
            <div class="overflow-x-auto">
              <table class="w-full text-xs">
                <thead>
                  <tr class="text-left text-[10px] text-slate-600 uppercase tracking-wider border-b border-slate-700/50">
                    <th class="pb-2 pr-4">Type</th>
                    <th class="pb-2 pr-4">Number</th>
                    <th class="pb-2 pr-4">Product</th>
                    <th class="pb-2 pr-4">Status</th>
                    <th class="pb-2 pr-4">Branch</th>
                    <th class="pb-2 pr-4 text-right">Balance</th>
                    <th class="pb-2 pr-4 text-right">Outstanding</th>
                  </tr>
                </thead>
                <tbody>
                  {#each profile.accounts as acct}
                    <tr class="border-b border-slate-700/20 hover:bg-slate-700/20">
                      <td class="py-2 pr-4 text-slate-400">{acct.type}</td>
                      <td class="py-2 pr-4 font-mono text-slate-300">{acct.number}</td>
                      <td class="py-2 pr-4 text-slate-300">{acct.productName}</td>
                      <td class="py-2 pr-4">
                        <span class="px-1.5 py-0.5 rounded text-[10px] capitalize {
                          ['closed', 'cancelled'].includes(acct.status?.toLowerCase())
                            ? 'bg-red-500/20 text-red-300'
                            : acct.status?.toLowerCase() === 'active' ? 'bg-emerald-500/20 text-emerald-300'
                            : 'bg-slate-600/20 text-slate-400'
                        }">
                          {acct.status}
                        </span>
                      </td>
                      <td class="py-2 pr-4 text-slate-500">{acct.branch}</td>
                      <td class="py-2 pr-4 text-right text-slate-300 tabular-nums">{acct.lastBalance != null ? phpFormat.format(acct.lastBalance) : '--'}</td>
                      <td class="py-2 pr-4 text-right tabular-nums {(acct.outstandingBalance || 0) > 0 ? 'text-red-400' : 'text-slate-500'}">
                        {acct.outstandingBalance ? phpFormat.format(acct.outstandingBalance) : '--'}
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          </div>
        {/if}

        <!-- Loans -->
        {#if profile.loans?.length}
          <div class="bg-[#1E293B] border border-slate-700/50 rounded-xl p-5">
            <div class="flex items-center justify-between mb-3">
              <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                Loans <span class="text-slate-600 font-normal">({profile.loans.length})</span>
              </h3>
              <span class="text-xs text-red-400 font-medium">
                Total Exposure: {phpFormat.format(exposure)}
              </span>
            </div>
            <div class="grid grid-cols-1 lg:grid-cols-2 gap-3">
              {#each profile.loans as loan}
                <div class="p-3 bg-slate-800/40 rounded-lg border border-slate-700/30">
                  <div class="flex items-center justify-between mb-2">
                    <div class="flex items-center gap-2">
                      <span class="text-sm font-medium text-slate-200">{loan.productName}</span>
                      <span class="text-[10px] px-1.5 py-0.5 rounded capitalize {
                        loan.status?.toLowerCase() === 'defaulted' ? 'bg-red-500/20 text-red-300'
                        : loan.status?.toLowerCase() === 'current' ? 'bg-emerald-500/20 text-emerald-300'
                        : 'bg-slate-600/20 text-slate-400'
                      }">{loan.status}</span>
                    </div>
                    <span class="text-[10px] text-slate-600 font-mono">{loan.loanId}</span>
                  </div>
                  <div class="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                    <div>
                      <p class="text-[10px] text-slate-600">Principal</p>
                      <p class="text-slate-300 tabular-nums">{phpFormat.format(loan.principalAmount)}</p>
                    </div>
                    <div>
                      <p class="text-[10px] text-slate-600">Outstanding</p>
                      <p class="text-red-400 font-medium tabular-nums">{phpFormat.format(loan.outstandingBalance)}</p>
                    </div>
                    <div>
                      <p class="text-[10px] text-slate-600">Rate / Term</p>
                      <p class="text-slate-300">{loan.interestRate}% / {loan.term}</p>
                    </div>
                    <div>
                      <p class="text-[10px] text-slate-600">Missed Payments</p>
                      <p class="{loan.missedPayments > 0 ? 'text-amber-400' : 'text-slate-500'}">{loan.missedPayments}</p>
                    </div>
                  </div>
                  {#if loan.defaultedAt}
                    <p class="text-[10px] text-red-400 mt-2">Defaulted: {formatDate(loan.defaultedAt)}</p>
                  {/if}
                </div>
              {/each}
            </div>
          </div>
        {/if}

        <!-- Negative History Timeline -->
        {#if profile.negativeReasons?.length}
          <div class="bg-[#1E293B] border border-slate-700/50 rounded-xl p-5">
            <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-4">Negative History</h3>
            <div class="relative pl-8">
              <div class="timeline-line"></div>
              {#each [...profile.negativeReasons].sort((a, b) => new Date(b.dateRecorded).getTime() - new Date(a.dateRecorded).getTime()) as reason}
                <div class="relative mb-5 last:mb-0">
                  <div class="absolute -left-8 top-0.5 w-[30px] flex justify-center">
                    <div class="w-3 h-3 rounded-full border-2 {
                      reason.code === 'FRAUD_CONFIRMED' ? 'bg-rose-500 border-rose-400'
                      : reason.code === 'LOAN_DEFAULT' ? 'bg-red-500 border-red-400'
                      : reason.code === 'AML_FLAG' ? 'bg-purple-500 border-purple-400'
                      : reason.code === 'CC_CANCELLED' ? 'bg-orange-500 border-orange-400'
                      : 'bg-slate-500 border-slate-400'
                    }"></div>
                  </div>
                  <div>
                    <div class="flex items-center gap-2 mb-1">
                      <span class="text-[10px] px-2 py-0.5 rounded-full border font-medium {reasonColor(reason.code)}">
                        {reason.code}
                      </span>
                      <span class="text-[10px] px-1.5 py-0.5 rounded capitalize {
                        reason.status?.toLowerCase() === 'resolved' ? 'bg-emerald-500/20 text-emerald-300'
                        : 'bg-red-500/20 text-red-300'
                      }">{reason.status}</span>
                    </div>
                    <p class="text-sm text-slate-300">{reason.description}</p>
                    <div class="flex items-center gap-4 mt-1 text-xs text-slate-500">
                      <span class="text-red-400 font-medium tabular-nums">{phpFormat.format(reason.amount)}</span>
                      <span>{reason.productType}</span>
                      <span>{formatDate(reason.dateRecorded)}</span>
                      <span class="font-mono text-[10px]">{reason.accountRef}</span>
                    </div>
                  </div>
                </div>
              {/each}
            </div>
          </div>
        {/if}

        <!-- Watchlist Sources -->
        {#if profile.watchlistSources?.length}
          <div class="bg-[#1E293B] border border-slate-700/50 rounded-xl p-5">
            <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Watchlist Sources</h3>
            <div class="grid grid-cols-2 md:grid-cols-3 gap-2">
              {#each profile.watchlistSources as ws}
                <div class="p-2.5 bg-slate-800/40 rounded-lg border border-slate-700/30 flex items-center justify-between">
                  <div>
                    <p class="text-xs text-slate-300 font-medium">{ws.source}</p>
                    <p class="text-[10px] text-slate-500">{ws.category}</p>
                  </div>
                  <div class="flex flex-col items-end">
                    <span class="w-2 h-2 rounded-full {ws.isActive ? 'bg-red-400' : 'bg-slate-600'}"></span>
                    <span class="text-[9px] text-slate-600 mt-0.5">{formatDate(ws.addedAt)}</span>
                  </div>
                </div>
              {/each}
            </div>
          </div>
        {/if}

        <!-- Addresses -->
        {#if profile.addresses?.length}
          <div class="bg-[#1E293B] border border-slate-700/50 rounded-xl p-5">
            <h3 class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">Addresses</h3>
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
              {#each profile.addresses as addr}
                <div class="p-3 bg-slate-800/40 rounded-lg border border-slate-700/30">
                  <p class="text-[10px] text-slate-500 uppercase tracking-wider mb-1">{addr.type}</p>
                  <p class="text-sm text-slate-300">{addr.line1}</p>
                  {#if addr.barangay}
                    <p class="text-xs text-slate-400">Brgy. {addr.barangay}</p>
                  {/if}
                  <p class="text-xs text-slate-400">{addr.city}, {addr.province} {addr.postalCode}</p>
                  <p class="text-xs text-slate-500">{addr.country}</p>
                </div>
              {/each}
            </div>
          </div>
        {/if}

        <!-- Audit Trail -->
        {#if profile.auditTrail?.length}
          <details class="bg-[#1E293B] border border-slate-700/50 rounded-xl overflow-hidden">
            <summary class="p-5 cursor-pointer text-xs font-semibold text-slate-400 uppercase tracking-wider hover:bg-slate-700/20 transition-colors">
              Audit Trail <span class="text-slate-600 font-normal">({profile.auditTrail.length} entries)</span>
            </summary>
            <div class="px-5 pb-5">
              <div class="space-y-2">
                {#each profile.auditTrail as entry}
                  <div class="flex items-start gap-3 p-2 rounded bg-slate-800/30">
                    <div class="shrink-0 mt-0.5">
                      <div class="w-2 h-2 rounded-full bg-slate-500"></div>
                    </div>
                    <div class="flex-1 min-w-0">
                      <div class="flex items-center gap-2">
                        <span class="text-xs text-slate-300 font-medium">{entry.action}</span>
                        <span class="text-[10px] text-slate-600">by {entry.performedBy}</span>
                      </div>
                      <p class="text-[10px] text-slate-500 mt-0.5">{entry.notes}</p>
                    </div>
                    <span class="text-[10px] text-slate-600 shrink-0">{formatDateTime(entry.timestamp)}</span>
                  </div>
                {/each}
              </div>
            </div>
          </details>
        {/if}

      </div>
    {/if}
  </main>

  <!-- Document Drawer -->
  {#if showDocDrawer && profile}
    <div class="drawer-overlay" onclick={() => { showDocDrawer = false; }} role="presentation"></div>
    <div class="drawer-panel">
      <!-- Header -->
      <div class="sticky top-0 bg-gradient-to-r from-[#0F172A] to-[#1E293B] border-b border-slate-700/50 px-5 py-4 flex items-center justify-between z-10">
        <div class="flex items-center gap-3">
          <div class="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
            <svg class="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" /></svg>
          </div>
          <div>
            <h3 class="text-sm font-semibold text-white">Document Inspector</h3>
            <p class="text-[10px] text-slate-500">Entity Profile</p>
          </div>
        </div>
        <button
          class="w-8 h-8 rounded-lg bg-slate-800/80 hover:bg-slate-700 flex items-center justify-center text-slate-400 hover:text-white transition-all hover:rotate-90 duration-200"
          onclick={() => { showDocDrawer = false; }}
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
          { key: 'document', label: 'Document', icon: '&#123;&#125;' },
          { key: 'response', label: 'Response', icon: '&#8617;' }
        ] as tab}
          <button
            class="flex-1 px-2.5 py-2.5 text-[10px] font-medium transition-all border-b-2 {
              docDrawerTab === tab.key
                ? 'text-emerald-400 border-emerald-400 bg-emerald-400/5'
                : 'text-slate-500 border-transparent hover:text-slate-300 hover:bg-slate-800/30'
            }"
            onclick={() => { docDrawerTab = tab.key as typeof docDrawerTab; }}
          >
            <span class="mr-0.5">{@html tab.icon}</span> {tab.label}
          </button>
        {/each}
      </div>

      <div class="flex-1 overflow-y-auto">

        <!-- ═══ TAB: MongoDB Query ═══ -->
        {#if docDrawerTab === 'query'}
          <div class="p-5">
            <!-- Pill badges -->
            <div class="flex items-center gap-2 mb-4">
              <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                findOne
              </span>
              <span class="inline-flex items-center px-2.5 py-1 rounded-full text-[10px] font-medium bg-slate-700/50 text-slate-400 border border-slate-600/30">
                collection: negative_list
              </span>
              {#if profileMeta?.documentSizeBytes}
                <span class="inline-flex items-center px-2.5 py-1 rounded-full text-[10px] font-medium bg-slate-700/50 text-slate-400 border border-slate-600/30">
                  {(profileMeta.documentSizeBytes / 1024).toFixed(1)} KB
                </span>
              {/if}
            </div>

            <!-- db.collection header -->
            <div class="flex items-center justify-between mb-2">
              <span class="text-[10px] text-slate-500 uppercase tracking-widest font-semibold">Query</span>
              <button
                class="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] text-slate-500 hover:text-emerald-400 hover:bg-emerald-400/5 transition-all"
                onclick={() => copyToClipboard(`db.getCollection("negative_list").findOne(\n${JSON.stringify(profileMeta?.query || { entityId: profile?.entityId }, null, 2)}\n)`)}
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
                <span class="text-[10px] text-slate-500 font-mono ml-2">mongosh</span>
              </div>
              <pre class="p-4 text-xs leading-relaxed overflow-x-auto overflow-y-auto max-h-[60vh] font-mono"><code><span class="text-slate-500">// Fetch a single entity profile by ID</span>
<span class="text-cyan-400">db</span>.<span class="text-emerald-400">getCollection</span>(<span class="text-amber-300">"negative_list"</span>).<span class="text-emerald-400">findOne</span>(
{@html syntaxHighlightJson(profileMeta?.query || { entityId: profile?.entityId })}
)</code></pre>
            </div>

            <p class="text-[10px] text-slate-600 mt-3 flex items-center gap-1.5">
              <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>
              One simple query to fetch the full customer profile. Paste directly in MongoDB Compass or mongosh.
            </p>
          </div>

        <!-- ═══ TAB: API Call ═══ -->
        {:else if docDrawerTab === 'api'}
          <div class="p-5">
            <div class="flex items-center justify-between mb-4">
              <div class="flex items-center gap-2">
                <span class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-bold tracking-wide bg-blue-500/10 text-blue-400 border border-blue-500/20">GET</span>
                <span class="text-xs text-slate-400 font-mono">/api/negative-list/profile/{profile.entityId}</span>
              </div>
              <button
                class="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] text-slate-500 hover:text-emerald-400 hover:bg-emerald-400/5 transition-all"
                onclick={() => copyToClipboard(`${BASE}/profile/${profile?.entityId}`)}
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
                <span class="text-[10px] text-slate-500 font-mono ml-2">request</span>
              </div>
              <pre class="p-4 text-xs leading-relaxed overflow-x-auto font-mono"><code><span class="text-cyan-400">GET</span> <span class="text-emerald-400">/api/negative-list/profile/{profile.entityId}</span></code></pre>
            </div>

            <!-- Curl -->
            <div class="mt-5">
              <div class="flex items-center justify-between mb-2">
                <span class="text-[10px] text-slate-500 uppercase tracking-widest font-semibold">cURL</span>
                <button
                  class="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] text-slate-500 hover:text-emerald-400 hover:bg-emerald-400/5 transition-all"
                  onclick={() => copyToClipboard(`curl "${BASE}/profile/${profile?.entityId}"`)}
                >
                  <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>
                  Copy
                </button>
              </div>
              <div class="relative rounded-xl overflow-hidden border border-slate-700/40 bg-[#0D1117]">
                <pre class="p-4 text-[11px] leading-relaxed overflow-x-auto font-mono text-slate-400"><code>curl <span class="text-emerald-400">"{BASE}/profile/{profile?.entityId}"</span></code></pre>
              </div>
            </div>
          </div>

        <!-- ═══ TAB: Document ═══ -->
        {:else if docDrawerTab === 'document'}
          <div class="p-5">
            <div class="flex items-center justify-between mb-2">
              <span class="text-[10px] text-slate-500 uppercase tracking-widest font-semibold">Raw MongoDB Document</span>
              <button
                class="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] text-slate-500 hover:text-emerald-400 hover:bg-emerald-400/5 transition-all"
                onclick={() => copyToClipboard(JSON.stringify(profile, null, 2))}
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
                <span class="text-[10px] text-slate-500 font-mono ml-2">document.json</span>
              </div>
              <pre class="p-4 text-xs leading-relaxed overflow-x-auto overflow-y-auto max-h-[65vh] font-mono"><code>{@html syntaxHighlightJson(profile)}</code></pre>
            </div>
          </div>

        <!-- ═══ TAB: Response ═══ -->
        {:else if docDrawerTab === 'response'}
          <div class="p-5">
            <div class="flex items-center justify-between mb-2">
              <span class="text-[10px] text-slate-500 uppercase tracking-widest font-semibold">Full API Response</span>
              <button
                class="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] text-slate-500 hover:text-emerald-400 hover:bg-emerald-400/5 transition-all"
                onclick={() => copyToClipboard(JSON.stringify({ _meta: profileMeta, profile }, null, 2))}
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
              <pre class="p-4 text-xs leading-relaxed overflow-x-auto overflow-y-auto max-h-[65vh] font-mono"><code>{@html syntaxHighlightJson({ _meta: profileMeta, profile })}</code></pre>
            </div>
          </div>
        {/if}
      </div>
    </div>
  {/if}

</div>
