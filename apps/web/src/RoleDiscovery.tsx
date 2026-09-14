import { useCallback, useEffect, useState } from 'react';
import {
  Compass,
  ExternalLink,
  RefreshCw,
  Search,
  Sparkles,
  Target,
  ThumbsDown,
  ThumbsUp,
  TrendingUp,
  Puzzle,
  Copy,
  Check,
  Trash2,
} from 'lucide-react';

interface RoleSummary {
  id: string;
  title: string;
  fitScore: number;
  confidence: number;
  category: string;
  roleFamily: string;
  reasoningSummary: string;
  strengths: string[];
  gaps: string[];
  equivalentTitles: string[];
  searchQueries: string[];
  industries: string[];
  companyTypes: string[];
  proposalStatus: string;
  searchCount?: number;
}

interface SearchStats {
  searchesOpened: number;
  jobsImported: number;
  highMatchJobsImported: number;
  applicationsGenerated: number;
  interviewsProduced: number;
  averageMatchScore: number;
}

interface SearchSpec {
  id: string;
  label: string;
  query: string;
  provider: string;
  location: string | null;
  remote: boolean | null;
  priority: number;
  status: string;
  isExploratory: boolean;
  url: string | null;
  stats: SearchStats;
}

interface RoleMapResponse {
  exists: boolean;
  message?: string;
  version?: number;
  generatedBy?: string;
  generatedAt?: string;
  notes?: string;
  capabilityGaps?: { capability: string; severity: string; whyItMatters: string }[];
  primary: RoleSummary[];
  secondary: RoleSummary[];
  exploratory: RoleSummary[];
  avoid: RoleSummary[];
  proposed: RoleSummary[];
}

interface ExtensionSettings {
  dashboard_url: string;
  import_prepares_application: boolean;
  high_match_threshold: number;
}

interface TokenRow {
  id: string;
  name: string;
  prefix: string;
  revoked: boolean;
  lastUsedAt: string | null;
}

const PROVIDER_LABELS: Record<string, string> = {
  linkedin: 'LinkedIn',
  infojobs: 'InfoJobs',
  google: 'Google',
  indeed: 'Indeed',
  'generic-web': 'Web',
};

function scoreColor(score: number): string {
  if (score >= 85) return 'text-emerald-400';
  if (score >= 70) return 'text-indigo-300';
  if (score >= 55) return 'text-amber-400';
  return 'text-slate-400';
}

function extensionInstalled(): boolean {
  return Boolean(document.documentElement.dataset.jobAgentExtension);
}

export default function RoleDiscovery({
  showToast,
}: {
  showToast: (text: string, type?: 'info' | 'success' | 'error') => void;
}) {
  const [roleMap, setRoleMap] = useState<RoleMapResponse | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [searchesByRole, setSearchesByRole] = useState<Record<string, SearchSpec[]>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [tokens, setTokens] = useState<TokenRow[]>([]);
  const [newToken, setNewToken] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [extensionSettings, setExtensionSettings] = useState<ExtensionSettings | null>(null);

  const fetchRoleMap = useCallback(async () => {
    try {
      const res = await fetch('/api/roles/map');
      if (res.ok) setRoleMap(await res.json());
    } catch {
      // offline fallback
    }
  }, []);

  const fetchTokens = useCallback(async () => {
    try {
      const res = await fetch('/api/extension/tokens');
      if (res.ok) {
        const data = await res.json();
        setTokens(data.tokens ?? []);
      }
    } catch {
      // offline fallback
    }
  }, []);

  const fetchExtensionSettings = useCallback(async () => {
    try {
      const res = await fetch('/api/extension/settings');
      if (res.ok) setExtensionSettings(await res.json());
    } catch {
      // offline fallback
    }
  }, []);

  useEffect(() => {
    void fetchRoleMap();
    void fetchTokens();
    void fetchExtensionSettings();
  }, [fetchRoleMap, fetchTokens, fetchExtensionSettings]);

  const togglePrepareOnImport = async (value: boolean) => {
    setBusy('settings');
    try {
      const res = await fetch('/api/extension/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ import_prepares_application: value }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? `Error ${res.status}`);
      setExtensionSettings(data);
      showToast(
        value
          ? 'Importar una oferta preparará también el CV'
          : 'Importar solo guardará la oferta',
        'success',
      );
    } catch (error) {
      showToast(error instanceof Error ? error.message : String(error), 'error');
    } finally {
      setBusy(null);
    }
  };

  const post = async (path: string, label: string) => {
    setBusy(label);
    try {
      const res = await fetch(path, { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail ?? `Request failed (${res.status})`);
      showToast(data.summary ?? data.message ?? `${label} complete`, 'success');
      await fetchRoleMap();
      setSearchesByRole({});
      return data;
    } catch (error) {
      showToast(error instanceof Error ? error.message : String(error), 'error');
      return null;
    } finally {
      setBusy(null);
    }
  };

  const toggleRole = async (roleId: string) => {
    if (expanded === roleId) {
      setExpanded(null);
      return;
    }
    setExpanded(roleId);
    if (searchesByRole[roleId]) return;
    try {
      const res = await fetch(`/api/roles/${encodeURIComponent(roleId)}`);
      if (res.ok) {
        const data = await res.json();
        setSearchesByRole((current) => ({ ...current, [roleId]: data.searches ?? [] }));
      }
    } catch {
      showToast('Could not load the searches for this role', 'error');
    }
  };

  /**
   * Hands the search to the extension when it is installed, so the click is
   * attributed and the tab is tracked. Without it, the dashboard opens the URL.
   */
  const runSearch = (spec: SearchSpec) => {
    const detail = {
      queryId: spec.id,
      provider: spec.provider,
      url: spec.url,
      query: spec.query,
      location: spec.location,
      remote: spec.remote,
    };

    if (extensionInstalled()) {
      window.dispatchEvent(new CustomEvent('jobagent:open-search', { detail }));
      return;
    }
    if (spec.url) window.open(spec.url, '_blank', 'noopener,noreferrer');
    void fetch(`/api/searches/${encodeURIComponent(spec.id)}/opened`, { method: 'POST' });
  };

  const createToken = async () => {
    setBusy('token');
    try {
      const res = await fetch('/api/extension/tokens', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: 'Browser extension' }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? 'Could not create a token');
      setNewToken(data.token);
      await fetchTokens();
    } catch (error) {
      showToast(error instanceof Error ? error.message : String(error), 'error');
    } finally {
      setBusy(null);
    }
  };

  const revokeToken = async (id: string) => {
    await fetch(`/api/extension/tokens/${encodeURIComponent(id)}`, { method: 'DELETE' });
    await fetchTokens();
    showToast('Token revoked', 'success');
  };

  const renderRole = (role: RoleSummary, tone: string) => {
    const isOpen = expanded === role.id;
    const searches = searchesByRole[role.id] ?? [];

    return (
      <div key={role.id} className="border border-slate-800 rounded-xl overflow-hidden bg-slate-900/60">
        <button
          onClick={() => void toggleRole(role.id)}
          className="w-full flex items-center gap-4 px-4 py-3 text-left hover:bg-slate-800/60 transition"
        >
          <div className={`text-2xl font-bold tabular-nums ${scoreColor(role.fitScore)}`}>
            {role.fitScore}
          </div>
          <div className="min-w-0 flex-1">
            <div className="font-semibold truncate">{role.title}</div>
            <div className="text-xs text-slate-400 truncate">
              {role.roleFamily || tone}
              {role.searchCount ? ` · ${role.searchCount} searches` : ''}
            </div>
          </div>
          {role.proposalStatus === 'proposed' && (
            <span className="text-[10px] uppercase tracking-wider px-2 py-1 rounded-full bg-amber-500/15 text-amber-400 border border-amber-500/30">
              proposed
            </span>
          )}
          <Search className="w-4 h-4 text-slate-500 shrink-0" />
        </button>

        {isOpen && (
          <div className="px-4 pb-4 space-y-4 border-t border-slate-800 pt-3">
            {role.reasoningSummary && (
              <p className="text-sm text-slate-300">{role.reasoningSummary}</p>
            )}

            <div className="grid sm:grid-cols-2 gap-3 text-xs">
              {role.strengths.length > 0 && (
                <div>
                  <div className="uppercase tracking-wider text-slate-500 mb-1">Strengths</div>
                  <ul className="space-y-0.5 text-slate-300">
                    {role.strengths.slice(0, 6).map((item) => (
                      <li key={item}>· {item}</li>
                    ))}
                  </ul>
                </div>
              )}
              {role.gaps.length > 0 && (
                <div>
                  <div className="uppercase tracking-wider text-slate-500 mb-1">Gaps</div>
                  <ul className="space-y-0.5 text-slate-300">
                    {role.gaps.slice(0, 6).map((item) => (
                      <li key={item}>· {item}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>

            {role.equivalentTitles.length > 0 && (
              <div className="text-xs text-slate-400">
                <span className="uppercase tracking-wider text-slate-500">Also called </span>
                {role.equivalentTitles.join(', ')}
              </div>
            )}

            <div>
              <div className="uppercase tracking-wider text-slate-500 text-xs mb-2">Searches</div>
              {searches.length === 0 ? (
                <p className="text-xs text-slate-500">
                  No searches for this role yet. Use Regenerate searches above.
                </p>
              ) : (
                <div className="space-y-2">
                  {searches.map((spec) => (
                    <div
                      key={spec.id}
                      className="flex items-center gap-3 bg-slate-950/60 border border-slate-800 rounded-lg px-3 py-2"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium truncate">
                          {spec.label}
                          {spec.isExploratory && (
                            <span className="ml-2 text-[10px] uppercase tracking-wider text-amber-400">
                              explore
                            </span>
                          )}
                        </div>
                        <div className="text-[11px] text-slate-500 truncate">
                          {PROVIDER_LABELS[spec.provider] ?? spec.provider}
                          {spec.location ? ` · ${spec.location}` : ''}
                          {spec.remote ? ' · remote' : ''}
                          {` · priority ${spec.priority}`}
                          {spec.status !== 'active' ? ` · ${spec.status}` : ''}
                          {spec.stats.jobsImported > 0
                            ? ` · ${spec.stats.jobsImported} imported, avg ${spec.stats.averageMatchScore}`
                            : ''}
                        </div>
                      </div>
                      <button
                        onClick={() => runSearch(spec)}
                        disabled={!spec.url}
                        className="shrink-0 flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 transition"
                      >
                        <ExternalLink className="w-3.5 h-3.5" />
                        Search
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {role.proposalStatus === 'proposed' && (
              <div className="flex gap-2">
                <button
                  onClick={() => void post(`/api/roles/${encodeURIComponent(role.id)}/accept`, 'Role accepted')}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 transition"
                >
                  <ThumbsUp className="w-3.5 h-3.5" /> Accept role
                </button>
                <button
                  onClick={() => void post(`/api/roles/${encodeURIComponent(role.id)}/reject`, 'Role rejected')}
                  className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 transition"
                >
                  <ThumbsDown className="w-3.5 h-3.5" /> Not for me
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  const group = (title: string, icon: JSX.Element, roles: RoleSummary[], tone: string) => {
    if (!roles.length) return null;
    return (
      <section className="mb-8">
        <div className="flex items-center gap-2 mb-3">
          {icon}
          <h3 className="text-xs uppercase tracking-widest text-slate-400">{title}</h3>
          <span className="text-xs text-slate-600">{roles.length}</span>
        </div>
        <div className="space-y-2">{roles.map((role) => renderRole(role, tone))}</div>
      </section>
    );
  };

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Your role map</h2>
          <p className="text-sm text-slate-400 mt-1 max-w-2xl">
            The agent reads your profile and master CV, works out which roles fit, and turns them
            into searches you can open with one click. You decide which results are worth importing.
          </p>
          {roleMap?.exists && (
            <p className="text-xs text-slate-500 mt-2">
              Version {roleMap.version} · {roleMap.generatedBy} ·{' '}
              {roleMap.generatedAt ? new Date(roleMap.generatedAt).toLocaleString() : ''}
            </p>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => void post('/api/roles/discover', 'Role discovery')}
            disabled={busy !== null}
            className="flex items-center gap-2 text-sm font-medium px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 transition"
          >
            <Sparkles className={`w-4 h-4 ${busy === 'Role discovery' ? 'animate-pulse' : ''}`} />
            {roleMap?.exists ? 'Rediscover roles' : 'Run role discovery'}
          </button>
          <button
            onClick={() => void post('/api/roles/searches/regenerate', 'Searches regenerated')}
            disabled={busy !== null || !roleMap?.exists}
            className="flex items-center gap-2 text-sm font-medium px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 disabled:opacity-50 transition"
          >
            <RefreshCw className="w-4 h-4" />
            Regenerate searches
          </button>
          <button
            onClick={() => void post('/api/roles/learn', 'Learning pass')}
            disabled={busy !== null || !roleMap?.exists}
            className="flex items-center gap-2 text-sm font-medium px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 disabled:opacity-50 transition"
          >
            <TrendingUp className="w-4 h-4" />
            Learn from imports
          </button>
        </div>
      </div>

      {!roleMap?.exists && (
        <div className="border border-slate-800 rounded-2xl p-6 bg-slate-900/60 mb-8">
          <p className="text-sm text-slate-300">
            {roleMap?.message ??
              'No role map yet. Run role discovery to work out which roles you should be searching for.'}
          </p>
        </div>
      )}

      {group('Primary', <Target className="w-4 h-4 text-emerald-400" />, roleMap?.primary ?? [], 'Primary')}
      {group('Secondary', <Compass className="w-4 h-4 text-indigo-400" />, roleMap?.secondary ?? [], 'Secondary')}
      {group('Exploratory', <Sparkles className="w-4 h-4 text-amber-400" />, roleMap?.exploratory ?? [], 'Exploratory')}
      {group('Proposed from imports', <TrendingUp className="w-4 h-4 text-amber-400" />, roleMap?.proposed ?? [], 'Proposed')}
      {group('Roles to avoid', <ThumbsDown className="w-4 h-4 text-slate-500" />, roleMap?.avoid ?? [], 'Avoid')}

      {(roleMap?.capabilityGaps?.length ?? 0) > 0 && (
        <section className="mb-8">
          <h3 className="text-xs uppercase tracking-widest text-slate-400 mb-3">Capability gaps</h3>
          <div className="space-y-2">
            {roleMap!.capabilityGaps!.slice(0, 6).map((gap) => (
              <div
                key={gap.capability}
                className="border border-slate-800 rounded-xl px-4 py-3 bg-slate-900/60"
              >
                <div className="flex items-center gap-2">
                  <span className="font-medium text-sm">{gap.capability}</span>
                  <span className="text-[10px] uppercase tracking-wider text-slate-500">
                    {gap.severity}
                  </span>
                </div>
                {gap.whyItMatters && (
                  <p className="text-xs text-slate-400 mt-1">{gap.whyItMatters}</p>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="border border-slate-800 rounded-2xl p-5 bg-slate-900/60">
        <div className="flex items-center gap-2 mb-2">
          <Puzzle className="w-4 h-4 text-indigo-400" />
          <h3 className="text-sm font-semibold">Browser extension</h3>
          {extensionInstalled() && (
            <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
              installed
            </span>
          )}
        </div>
        <p className="text-xs text-slate-400 mb-4 max-w-2xl">
          Create a pairing token and paste it into the extension's options page. The extension shows
          these searches in your browser and imports a job with one click. It never stores your job
          board passwords.
        </p>

        {newToken && (
          <div className="mb-4 p-3 rounded-xl bg-slate-950 border border-indigo-500/40">
            <div className="text-xs text-slate-400 mb-2">
              Copy this token now. It is not shown again.
            </div>
            <div className="flex items-center gap-2">
              <code className="text-xs font-mono text-indigo-300 break-all flex-1">{newToken}</code>
              <button
                onClick={() => {
                  void navigator.clipboard.writeText(newToken);
                  setCopied(true);
                  setTimeout(() => setCopied(false), 2000);
                }}
                className="shrink-0 p-2 rounded-lg bg-slate-800 hover:bg-slate-700 transition"
              >
                {copied ? (
                  <Check className="w-3.5 h-3.5 text-emerald-400" />
                ) : (
                  <Copy className="w-3.5 h-3.5" />
                )}
              </button>
            </div>
          </div>
        )}

        {extensionSettings && (
          <label className="flex items-start gap-3 mb-4 p-3 rounded-xl bg-slate-950/60 border border-slate-800 cursor-pointer">
            <input
              type="checkbox"
              checked={extensionSettings.import_prepares_application}
              disabled={busy !== null}
              onChange={(event) => void togglePrepareOnImport(event.target.checked)}
              className="mt-0.5"
            />
            <span className="text-xs text-slate-300">
              <strong className="text-slate-100">Preparar el CV al importar.</strong> Al pulsar
              Importar oferta, el agente adapta tu CV maestro a esa oferta y te deja el PDF listo
              para descargar desde la extensión. Las ofertas con match bajo se saltan este paso.
            </span>
          </label>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={() => void createToken()}
            disabled={busy !== null}
            className="text-sm font-medium px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 transition"
          >
            Create pairing token
          </button>
          <span className="text-xs text-slate-500">
            {tokens.filter((token) => !token.revoked).length} active
          </span>
        </div>

        {tokens.length > 0 && (
          <div className="mt-4 space-y-2">
            {tokens.map((token) => (
              <div
                key={token.id}
                className="flex items-center gap-3 text-xs bg-slate-950/60 border border-slate-800 rounded-lg px-3 py-2"
              >
                <code className="font-mono text-slate-400">{token.prefix}…</code>
                <span className="text-slate-500 flex-1 truncate">
                  {token.name}
                  {token.lastUsedAt
                    ? ` · last used ${new Date(token.lastUsedAt).toLocaleString()}`
                    : ' · never used'}
                </span>
                {token.revoked ? (
                  <span className="text-slate-600">revoked</span>
                ) : (
                  <button
                    onClick={() => void revokeToken(token.id)}
                    className="p-1.5 rounded-md hover:bg-slate-800 text-slate-400 hover:text-red-400 transition"
                    title="Revoke"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
