const BASE = 'http://localhost:8000/api/negative-list';

export type SearchMode = 'fuzzy' | 'semantic';

export interface SearchParams {
  q: string;
  mode?: SearchMode;
  max_edits?: number;
  limit?: number;
  dob?: string;
  national_id?: string;
}

export interface PostSearchParams {
  query: string;
  mode?: SearchMode;
  filters?: Record<string, string[]>;
  dob?: string;
  national_id?: string;
  max_edits?: number;
  limit?: number;
  cursor?: string | null;
  direction?: string;
  use_facets?: boolean;
}

export interface ApiMeta {
  executionTimeMs: number;
  collection: string;
  query?: Record<string, unknown>;
  pipeline?: Record<string, unknown>[];
  index?: string;
  searchMode?: string;
  resultsCount?: number;
  total?: number;
  documentSizeBytes?: number;
}

export interface PaginationInfo {
  limit: number;
  hasMore: boolean;
  cursor: string | null;
  totalCount: number;
  currentPageSize: number;
}

export interface FacetBucket {
  value: string;
  count: number;
}

export interface Facet {
  field: string;
  label: string;
  buckets: FacetBucket[];
}

export interface PaginatedSearchResponse {
  _meta: ApiMeta;
  results: NegativeEntry[];
  pagination: PaginationInfo;
  facets: Facet[];
}

export interface SearchResponse {
  _meta: ApiMeta;
  results: NegativeEntry[];
}

export interface ProfileResponse {
  _meta: ApiMeta;
  profile: NegativeEntry;
}

export interface StatsResponse {
  _meta: ApiMeta;
  profile: DashboardStats;
}

export interface NegativeEntry {
  _id: string;
  entityId: string;
  entityType: string;
  fullName: string;
  aliases: string[];
  dateOfBirth: string;
  gender: string;
  phone: string;
  email: string;
  civilStatus: string;
  nationality: string;
  identifiers: {
    nationalId: string;
    tin: string;
    sssNo: string;
    gsisNo: string | null;
    passportNo: string;
    driversLicense: string;
  };
  addresses: Address[];
  accounts: Account[];
  loans: Loan[];
  relationship: Relationship;
  kyc: KYC;
  negativeReasons: NegativeReason[];
  riskTags: string[];
  riskScore: number;
  watchlistSources: WatchlistSource[];
  auditTrail: AuditEntry[];
  isActive: boolean;
  createdAt: string;
  updatedAt: string;
  sourceSystem: string;
  score?: number;
}

export interface Address {
  type: string;
  line1: string;
  barangay?: string;
  city: string;
  province: string;
  postalCode: string;
  country: string;
}

export interface Account {
  type: string;
  number: string;
  productName: string;
  status: string;
  branch: string;
  openedAt: string;
  closedAt?: string;
  lastBalance: number;
  creditLimit?: number;
  outstandingBalance?: number;
  currency: string;
}

export interface Loan {
  type: string;
  loanId: string;
  productName: string;
  principalAmount: number;
  outstandingBalance: number;
  interestRate: number;
  term: string;
  status: string;
  disbursedAt: string;
  defaultedAt?: string;
  lastPaymentAt?: string;
  missedPayments: number;
  branch: string;
  currency: string;
}

export interface Relationship {
  customerId: string;
  since: string;
  tier: string;
  segment: string;
  branch: string;
  relationshipManager: string;
  status: string;
  previousStatus: string;
  blacklistedAt?: string;
}

export interface KYC {
  level: string;
  verifiedAt: string;
  idType: string;
  idNumber: string;
  riskRating: string;
  lastReviewedAt: string;
  pepStatus: boolean;
  fatcaReportable: boolean;
}

export interface NegativeReason {
  code: string;
  description: string;
  amount: number;
  currency: string;
  dateRecorded: string;
  productType: string;
  accountRef: string;
  status: string;
}

export interface WatchlistSource {
  source: string;
  category: string;
  addedAt: string;
  isActive: boolean;
}

export interface AuditEntry {
  action: string;
  performedBy: string;
  timestamp: string;
  notes: string;
}

export interface DashboardStats {
  total: number;
  active: number;
  resolved: number;
  totalExposure: number;
  byReason: { code: string; count: number }[];
  bySource: { source: string; count: number }[];
  byBranch: { branch: string; count: number }[];
  byEntityType: { type: string; count: number }[];
}

// ── POST search (primary — pagination + facets) ──────────────────

export async function postSearch(params: PostSearchParams): Promise<PaginatedSearchResponse> {
  const res = await fetch(`${BASE}/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query: params.query,
      mode: params.mode ?? 'fuzzy',
      filters: params.filters ?? {},
      dob: params.dob ?? null,
      national_id: params.national_id ?? null,
      max_edits: params.max_edits ?? 2,
      limit: params.limit ?? 20,
      cursor: params.cursor ?? null,
      direction: params.direction ?? 'next',
      use_facets: params.use_facets ?? true,
    }),
  });
  if (!res.ok) throw new Error(`Search failed: ${res.statusText}`);
  return res.json();
}

// ── GET search (legacy, simple) ──────────────────────────────────

export async function searchNegativeList(params: SearchParams): Promise<SearchResponse> {
  const url = new URL(`${BASE}/search`);
  url.searchParams.set('q', params.q);
  if (params.mode) url.searchParams.set('mode', params.mode);
  if (params.max_edits !== undefined) url.searchParams.set('max_edits', String(params.max_edits));
  if (params.limit) url.searchParams.set('limit', String(params.limit));
  if (params.dob) url.searchParams.set('dob', params.dob);
  if (params.national_id) url.searchParams.set('national_id', params.national_id);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Search failed: ${res.statusText}`);
  return res.json();
}

export async function autocomplete(q: string, limit = 8): Promise<SearchResponse> {
  const res = await fetch(`${BASE}/autocomplete?q=${encodeURIComponent(q)}&limit=${limit}`);
  if (!res.ok) throw new Error(`Autocomplete failed: ${res.statusText}`);
  return res.json();
}

export async function getProfile(entityId: string): Promise<ProfileResponse> {
  const res = await fetch(`${BASE}/profile/${encodeURIComponent(entityId)}`);
  if (!res.ok) throw new Error(`Profile fetch failed: ${res.statusText}`);
  return res.json();
}

export async function getStats(): Promise<StatsResponse> {
  const res = await fetch(`${BASE}/stats`);
  if (!res.ok) throw new Error(`Stats fetch failed: ${res.statusText}`);
  return res.json();
}

export async function getEntries(params: {
  limit?: number; skip?: number; reason?: string; source?: string; status?: string;
}): Promise<SearchResponse> {
  const url = new URL(`${BASE}/entries`);
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined) url.searchParams.set(k, String(v));
  });
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Entries fetch failed: ${res.statusText}`);
  return res.json();
}

export async function getIndexDefinitions(): Promise<{ _meta: ApiMeta; profile: Record<string, unknown> }> {
  const res = await fetch(`${BASE}/index-definitions`);
  if (!res.ok) throw new Error(`Index definitions fetch failed: ${res.statusText}`);
  return res.json();
}
