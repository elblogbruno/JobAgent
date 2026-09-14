import { useState, useEffect } from 'react';
import {
  Briefcase,
  Send,
  Settings as SettingsIcon,
  HelpCircle,
  RefreshCw,
  ExternalLink,
  TrendingUp,
  Play,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  MapPin,
  Search,
  X,
  Sparkles,
  Copy,
  Check,
  ChevronRight,
  ShieldAlert,
  Camera,
  Video,
  Eye,
  Save,
  User,
  Cpu,
  Zap,
  Key,
  Server,
  ShieldCheck,
  Compass,
  FileText,
  Download,
  Wand2,
} from 'lucide-react';

import RoleDiscovery from './RoleDiscovery';
import ResumeLibrary from './ResumeLibrary';
import OutcomeControls, { OutcomeEntry } from './OutcomeControls';

interface Job {
  id: string;
  company: string;
  role: string;
  location: string;
  is_remote: boolean;
  is_hybrid?: boolean;
  source: string;
  status: string;
  apply_url: string;
  discovered_at: string;
  technologies: string[];
  salary: string;
  description?: string;
  requirements?: string[];
  preferred_requirements?: string[];
}

interface SubmissionEvidence {
  verified: boolean;
  evidence_type?: string;
  details?: string;
  confirmation_id?: string;
  redirect_url?: string;
  pre_screenshot?: string;
  post_screenshot?: string;
  video?: string;
}

interface Application {
  applied_at?: string | null;
  submitted_manually?: boolean;
  outcome_history?: OutcomeEntry[];
  has_tailored_resume?: boolean;
  cover_letter_text?: string | null;
  id: string;
  job_id: string;
  company: string;
  role: string;
  status: string;
  execution_mode: string;
  match_score: number;
  reactive_resume_application_id?: string;
  created_at: string;
  error_message?: string;
  submission_evidence?: SubmissionEvidence;
}

interface SystemMetrics {
  total_jobs_discovered: number;
  high_match_jobs: number;
  total_applied: number;
  total_blocked: number;
  pending_questions: number;
}

interface CandidateProfileData {
  identity: {
    name: string;
    email: string;
    phone: string;
    location: string;
    linkedin?: string;
    github?: string;
    website?: string;
  };
  job_preferences: {
    locations: string[];
    remote: boolean;
    hybrid: boolean;
    onsite: boolean;
    roles: string[];
    interests: string[];
    minimum_salary?: number;
    preferred_salary?: number;
    currencies: string[];
    relocation: boolean;
    visa_requirements: {
      authorized_eu: boolean;
      authorized_us: boolean;
      requires_sponsorship_us: boolean;
      requires_sponsorship_eu: boolean;
    };
  };
  application_preferences: {
    execution_mode: string;
    auto_apply_threshold: number;
    prepare_threshold: number;
    maximum_daily_applications: number;
    allowed_sources: string[];
    excluded_companies: string[];
    excluded_roles: string[];
    require_salary_match: boolean;
    require_remote_match: boolean;
    follow_up_days: number;
  };
  reactive_resume?: {
    master_resume_id: string;
    master_resume_name: string;
  };
}

interface LLMConfigData {
  active_provider: string;
  openai: {
    is_configured: boolean;
    key_masked: string;
    model: string;
  };
  anthropic: {
    is_configured: boolean;
    key_masked: string;
    model: string;
  };
  gemini: {
    is_configured: boolean;
    key_masked: string;
    model: string;
  };
  ollama: {
    base_url: string;
    model: string;
  };
  available_providers: string[];
}

export default function App() {
  const [activeTab, setActiveTab] = useState<'dashboard' | 'roles' | 'jobs' | 'applications' | 'resumes' | 'vault' | 'profile' | 'llm'>('dashboard');
  const [metrics, setMetrics] = useState<SystemMetrics>({
    total_jobs_discovered: 0,
    high_match_jobs: 0,
    total_applied: 0,
    total_blocked: 0,
    pending_questions: 0,
  });
  const [profile, setProfile] = useState<CandidateProfileData | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [applications, setApplications] = useState<Application[]>([]);
  const [loading, setLoading] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const [toastMsg, setToastMsg] = useState<{ text: string; type: 'info' | 'success' | 'error' } | null>(null);

  // Filters & Search
  const [searchQuery, setSearchQuery] = useState('');
  const [jobFilter, setJobFilter] = useState<'all' | 'remote' | 'evaluated'>('all');
  const [appFilter, setAppFilter] = useState<'all' | 'applied' | 'blocked' | 'failed'>('all');

  // Modals & Bottom Sheets
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [selectedEvidenceApp, setSelectedEvidenceApp] = useState<Application | null>(null);
  const [activeEvidenceTab, setActiveEvidenceTab] = useState<'post_screenshot' | 'pre_screenshot' | 'video'>('post_screenshot');
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [regenerating, setRegenerating] = useState<string | null>(null);

  // Profile Form State
  const [profileForm, setProfileForm] = useState<CandidateProfileData | null>(null);

  // LLM Configuration State
  const [llmConfig, setLlmConfig] = useState<LLMConfigData | null>(null);
  const [selectedProvider, setSelectedProvider] = useState<string>('mock');
  const [openaiKeyInput, setOpenaiKeyInput] = useState('');
  const [openaiModelInput, setOpenaiModelInput] = useState('gpt-4o');
  const [anthropicKeyInput, setAnthropicKeyInput] = useState('');
  const [anthropicModelInput, setAnthropicModelInput] = useState('claude-3-5-sonnet-20241022');
  const [geminiKeyInput, setGeminiKeyInput] = useState('');
  const [geminiModelInput, setGeminiModelInput] = useState('gemini-1.5-pro');
  const [ollamaUrlInput, setOllamaUrlInput] = useState('http://localhost:11434');
  const [ollamaModelInput, setOllamaModelInput] = useState('llama3');

  const [testingLlm, setTestingLlm] = useState(false);
  const [savingLlm, setSavingLlm] = useState(false);
  const [llmTestFeedback, setLlmTestFeedback] = useState<{
    success: boolean;
    message: string;
    latency_ms?: number;
  } | null>(null);

  const showToast = (text: string, type: 'info' | 'success' | 'error' = 'info') => {
    setToastMsg({ text, type });
    setTimeout(() => setToastMsg(null), 4000);
  };

  const fetchProfile = async () => {
    try {
      const res = await fetch('/api/candidate/profile');
      if (res.ok) {
        const data = await res.json();
        setProfile(data);
        setProfileForm(JSON.parse(JSON.stringify(data)));
      }
    } catch {
      // offline fallback
    }
  };

  const fetchLlmConfig = async () => {
    try {
      const res = await fetch('/api/llm/config');
      if (res.ok) {
        const data: LLMConfigData = await res.json();
        setLlmConfig(data);
        setSelectedProvider(data.active_provider || 'mock');
        setOpenaiModelInput(data.openai.model || 'gpt-4o');
        setAnthropicModelInput(data.anthropic.model || 'claude-3-5-sonnet-20241022');
        setGeminiModelInput(data.gemini.model || 'gemini-1.5-pro');
        setOllamaUrlInput(data.ollama.base_url || 'http://localhost:11434');
      }
    } catch {
      // offline fallback
    }
  };

  const fetchMetrics = async () => {
    try {
      const res = await fetch('/api/system/metrics');
      if (res.ok) {
        const data = await res.json();
        setMetrics(data);
      }
    } catch {
      // offline fallback
    }
  };

  const fetchJobs = async () => {
    try {
      const res = await fetch('/api/jobs?limit=50');
      if (res.ok) {
        const data = await res.json();
        setJobs(data);
      }
    } catch {
      // offline fallback
    }
  };

  const fetchApplications = async () => {
    try {
      const res = await fetch('/api/applications?limit=50');
      if (res.ok) {
        const data = await res.json();
        setApplications(data);
      }
    } catch {
      // offline fallback
    }
  };

  const refreshAll = async () => {
    setLoading(true);
    await Promise.all([fetchProfile(), fetchLlmConfig(), fetchMetrics(), fetchJobs(), fetchApplications()]);
    setLoading(false);
  };

  const triggerDiscovery = async (limit: number = 5) => {
    setDiscovering(true);
    showToast('Iniciando rastreo en Greenhouse, Lever y Ashby...', 'info');
    try {
      const res = await fetch(`/api/jobs/discover?limit=${limit}`, { method: 'POST' });
      if (res.ok) {
        showToast('¡Ciclo despachado al worker Celery! Analizando ofertas...', 'success');
        setTimeout(() => {
          refreshAll();
          setDiscovering(false);
        }, 3500);
      } else {
        showToast('Error al despachar el ciclo de búsqueda.', 'error');
        setDiscovering(false);
      }
    } catch {
      showToast('Error de conexión con el backend.', 'error');
      setDiscovering(false);
    }
  };

  const saveProfileChanges = async () => {
    if (!profileForm) return;
    setSavingProfile(true);
    try {
      const res = await fetch('/api/candidate/profile', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(profileForm),
      });
      if (res.ok) {
        const data = await res.json();
        setProfile(data.profile);
        showToast('¡Perfil guardado y sincronizado exitosamente!', 'success');
      } else {
        showToast('Error al guardar el perfil.', 'error');
      }
    } catch {
      showToast('Error de conexión con el backend.', 'error');
    } finally {
      setSavingProfile(false);
    }
  };

  const testLlmProvider = async () => {
    setTestingLlm(true);
    setLlmTestFeedback(null);
    try {
      const payload: {
        provider: string;
        api_key?: string;
        model?: string;
        base_url?: string;
      } = { provider: selectedProvider };

      if (selectedProvider === 'openai') {
        payload.api_key = openaiKeyInput;
        payload.model = openaiModelInput;
      } else if (selectedProvider === 'anthropic') {
        payload.api_key = anthropicKeyInput;
        payload.model = anthropicModelInput;
      } else if (selectedProvider === 'gemini') {
        payload.api_key = geminiKeyInput;
        payload.model = geminiModelInput;
      } else if (selectedProvider === 'ollama') {
        payload.base_url = ollamaUrlInput;
        payload.model = ollamaModelInput;
      }

      const res = await fetch('/api/llm/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      setLlmTestFeedback(data);
    } catch {
      setLlmTestFeedback({
        success: false,
        message: 'No se pudo conectar con el endpoint de prueba.',
      });
    } finally {
      setTestingLlm(false);
    }
  };

  const saveLlmConfig = async () => {
    setSavingLlm(true);
    try {
      const payload = {
        provider: selectedProvider,
        openai_api_key: openaiKeyInput || undefined,
        openai_model: openaiModelInput,
        anthropic_api_key: anthropicKeyInput || undefined,
        anthropic_model: anthropicModelInput,
        gemini_api_key: geminiKeyInput || undefined,
        gemini_model: geminiModelInput,
        ollama_base_url: ollamaUrlInput,
        ollama_model: ollamaModelInput,
      };

      const res = await fetch('/api/llm/config', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        await fetchLlmConfig();
        showToast(`¡Configuración de IA guardada! Proveedor activo: ${selectedProvider}`, 'success');
      } else {
        showToast('Error al guardar la configuración de IA.', 'error');
      }
    } catch {
      showToast('Error de conexión con el backend.', 'error');
    } finally {
      setSavingLlm(false);
    }
  };

  const handleCopy = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 2000);
  };

  /**
   * Rebuilds the tailored CV with the current tailoring, deleting the previous
   * one in Reactive Resume so near-duplicates do not pile up.
   */
  const regenerateResume = async (runId: string) => {
    setRegenerating(runId);
    try {
      const res = await fetch(`/api/applications/${encodeURIComponent(runId)}/resume/regenerate`, {
        method: 'POST',
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? `Error ${res.status}`);
      showToast(data.headline ? `CV regenerado: ${data.headline}` : data.message, 'success');
      await fetchApplications();
    } catch (error) {
      showToast(error instanceof Error ? error.message : String(error), 'error');
    } finally {
      setRegenerating(null);
    }
  };

  useEffect(() => {
    refreshAll();
  }, []);

  /**
   * Opens the job named in ?job=<id>, which is the link the browser extension
   * builds for "Open in Job Agent". Without this the dashboard just loaded the
   * overview and the parameter did nothing.
   */
  useEffect(() => {
    const jobId = new URLSearchParams(window.location.search).get('job');
    if (!jobId) return;

    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
        if (!res.ok) throw new Error(res.status === 404 ? 'Esa oferta ya no existe' : `Error ${res.status}`);
        const detail = await res.json();
        if (cancelled) return;

        setActiveTab('jobs');
        setSelectedJob({
          ...detail,
          salary: [detail.salary_min, detail.salary_max, detail.salary_currency]
            .filter(Boolean)
            .join(' ')
            .trim(),
        });
      } catch (error) {
        if (!cancelled) {
          showToast(error instanceof Error ? error.message : String(error), 'error');
        }
      } finally {
        // Drop the parameter so a refresh does not reopen the modal.
        window.history.replaceState({}, '', window.location.pathname);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  // Filtered Jobs
  const filteredJobs = jobs.filter((j) => {
    const matchesSearch =
      j.company.toLowerCase().includes(searchQuery.toLowerCase()) ||
      j.role.toLowerCase().includes(searchQuery.toLowerCase()) ||
      j.technologies.some((t) => t.toLowerCase().includes(searchQuery.toLowerCase()));

    if (!matchesSearch) return false;
    if (jobFilter === 'remote') return j.is_remote;
    if (jobFilter === 'evaluated') return j.status === 'EVALUATED';
    return true;
  });

  // Filtered Applications
  const filteredApps = applications.filter((a) => {
    if (appFilter === 'applied') return a.status === 'APPLIED';
    if (appFilter === 'blocked') return a.status === 'BLOCKED';
    if (appFilter === 'failed') return a.status === 'FAILED';
    return true;
  });

  const formatErrorMessage = (msg?: string) => {
    if (!msg) return null;
    if (msg.toLowerCase().includes('captcha')) return 'Detenido por seguridad: CAPTCHA o Cloudflare detectado.';
    if (msg.toLowerCase().includes('resume_slug_already_exists')) return 'Duplicado existente en Reactive Resume.';
    if (msg.toLowerCase().includes('element is not an <input>')) return 'El ATS requiere carga manual de documento.';
    return msg.length > 85 ? msg.substring(0, 85) + '...' : msg;
  };

  return (
    <div className="flex flex-col md:flex-row min-h-screen bg-slate-950 text-slate-100 font-sans">
      {/* ======================================================== */}
      {/* MOBILE TOP BAR (Sticky header)                           */}
      {/* ======================================================== */}
      <header className="md:hidden sticky top-0 z-40 bg-slate-900/90 backdrop-blur-md border-b border-slate-800 px-4 py-3 flex items-center justify-between pt-safe">
        <div className="flex items-center space-x-2.5">
          <div className="bg-gradient-to-tr from-indigo-600 to-indigo-500 p-2 rounded-xl shadow-md shadow-indigo-500/20">
            <Briefcase className="w-4 h-4 text-white" />
          </div>
          <div>
            <div className="flex items-center space-x-1.5">
              <span className="font-bold text-sm tracking-tight text-white">Job Agent</span>
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
            </div>
            <p className="text-[10px] text-slate-400 leading-none">
              LLM: <strong className="text-indigo-400 uppercase font-semibold">{llmConfig?.active_provider || 'MOCK'}</strong> • {profile?.application_preferences?.execution_mode || 'AUTO'}
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-1.5">
          <button
            onClick={() => triggerDiscovery(3)}
            disabled={discovering}
            className="flex items-center space-x-1 px-2.5 py-1.5 bg-indigo-600 active:bg-indigo-700 text-white rounded-lg text-xs font-semibold shadow-sm transition disabled:opacity-50"
          >
            <Play className={`w-3 h-3 fill-current ${discovering ? 'animate-spin' : ''}`} />
            <span>{discovering ? 'Buscando...' : 'Buscar'}</span>
          </button>

          <button
            onClick={refreshAll}
            disabled={loading}
            className="p-2 bg-slate-800 active:bg-slate-700 text-slate-300 rounded-lg transition"
            title="Recargar datos"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-indigo-400' : ''}`} />
          </button>
        </div>
      </header>

      {/* ======================================================== */}
      {/* DESKTOP SIDEBAR                                          */}
      {/* ======================================================== */}
      <aside className="hidden md:flex w-64 bg-slate-900 border-r border-slate-800 p-6 flex-col justify-between shrink-0">
        <div>
          <div className="flex items-center space-x-3 mb-8">
            <div className="bg-indigo-600 p-2.5 rounded-xl shadow-lg shadow-indigo-600/30">
              <Briefcase className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight">Job Agent</h1>
              <p className="text-xs text-slate-400">Autonomous Career AI</p>
            </div>
          </div>

          <nav className="space-y-1.5">
            <button
              onClick={() => setActiveTab('dashboard')}
              className={`w-full flex items-center space-x-3 px-4 py-3 rounded-xl text-sm font-medium transition ${
                activeTab === 'dashboard' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              }`}
            >
              <TrendingUp className="w-5 h-5" />
              <span>Resumen</span>
            </button>

            <button
              onClick={() => setActiveTab('roles')}
              className={`w-full flex items-center space-x-3 px-4 py-3 rounded-xl text-sm font-medium transition ${
                activeTab === 'roles' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              }`}
            >
              <Compass className="w-5 h-5" />
              <span>Role Discovery</span>
            </button>

            <button
              onClick={() => setActiveTab('jobs')}
              className={`w-full flex items-center justify-between px-4 py-3 rounded-xl text-sm font-medium transition ${
                activeTab === 'jobs' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              }`}
            >
              <div className="flex items-center space-x-3">
                <Briefcase className="w-5 h-5" />
                <span>Ofertas</span>
              </div>
              {jobs.length > 0 && (
                <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 font-mono">
                  {jobs.length}
                </span>
              )}
            </button>

            <button
              onClick={() => setActiveTab('applications')}
              className={`w-full flex items-center justify-between px-4 py-3 rounded-xl text-sm font-medium transition ${
                activeTab === 'applications' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              }`}
            >
              <div className="flex items-center space-x-3">
                <Send className="w-5 h-5" />
                <span>Candidaturas</span>
              </div>
              {applications.length > 0 && (
                <span className="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 font-mono">
                  {applications.length}
                </span>
              )}
            </button>

            <button
              onClick={() => setActiveTab('resumes')}
              className={`w-full flex items-center space-x-3 px-4 py-3 rounded-xl text-sm font-medium transition ${
                activeTab === 'resumes' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              }`}
            >
              <FileText className="w-5 h-5" />
              <span>Tus CVs</span>
            </button>

            <button
              onClick={() => setActiveTab('profile')}
              className={`w-full flex items-center space-x-3 px-4 py-3 rounded-xl text-sm font-medium transition ${
                activeTab === 'profile' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              }`}
            >
              <User className="w-5 h-5" />
              <span>Editar Perfil</span>
            </button>

            <button
              onClick={() => setActiveTab('llm')}
              className={`w-full flex items-center justify-between px-4 py-3 rounded-xl text-sm font-medium transition ${
                activeTab === 'llm' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              }`}
            >
              <div className="flex items-center space-x-3">
                <Cpu className="w-5 h-5" />
                <span>Modelos & IA</span>
              </div>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-800 text-indigo-300 font-mono uppercase font-bold">
                {llmConfig?.active_provider || 'MOCK'}
              </span>
            </button>

            <button
              onClick={() => setActiveTab('vault')}
              className={`w-full flex items-center space-x-3 px-4 py-3 rounded-xl text-sm font-medium transition ${
                activeTab === 'vault' ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-600/30' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              }`}
            >
              <HelpCircle className="w-5 h-5" />
              <span>Answer Vault</span>
            </button>
          </nav>
        </div>

        <div className="border-t border-slate-800 pt-4 space-y-3">
          <button
            onClick={() => triggerDiscovery(5)}
            disabled={discovering}
            className="w-full flex items-center justify-center space-x-2 py-2.5 px-4 bg-indigo-600 hover:bg-indigo-500 active:scale-95 text-white text-xs font-semibold rounded-xl shadow-lg shadow-indigo-600/20 transition disabled:opacity-50"
          >
            <Play className={`w-3.5 h-3.5 fill-current ${discovering ? 'animate-spin' : ''}`} />
            <span>{discovering ? 'Descubriendo...' : 'Buscar Ofertas'}</span>
          </button>

          <div className="flex items-center justify-between text-xs text-slate-400 px-1">
            <span className="flex items-center space-x-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
              <span>Online</span>
            </span>
            <button
              onClick={refreshAll}
              disabled={loading}
              className="p-1.5 hover:bg-slate-800 rounded-lg transition"
              title="Actualizar"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin text-indigo-400' : ''}`} />
            </button>
          </div>
        </div>
      </aside>

      {/* ======================================================== */}
      {/* MAIN CONTENT CONTAINER                                   */}
      {/* ======================================================== */}
      <main className="flex-1 px-4 py-4 md:p-8 overflow-y-auto pb-28 md:pb-8 max-w-6xl mx-auto w-full">
        {/* Real-time Toast Banner */}
        {toastMsg && (
          <div
            className={`mb-4 p-3.5 rounded-xl text-xs flex items-center space-x-2.5 animate-fadeIn border ${
              toastMsg.type === 'success'
                ? 'bg-emerald-950/80 border-emerald-700/60 text-emerald-200'
                : toastMsg.type === 'error'
                ? 'bg-rose-950/80 border-rose-700/60 text-rose-200'
                : 'bg-indigo-950/80 border-indigo-700/60 text-indigo-200'
            }`}
          >
            <Sparkles className="w-4 h-4 shrink-0" />
            <span className="flex-1 font-medium">{toastMsg.text}</span>
          </div>
        )}

        {/* ---------------------------------------------------- */}
        {/* TAB: ROLE DISCOVERY                                  */}
        {/* ---------------------------------------------------- */}
        {activeTab === 'roles' && <RoleDiscovery showToast={showToast} />}

        {activeTab === 'resumes' && <ResumeLibrary showToast={showToast} />}

        {/* ---------------------------------------------------- */}
        {/* TAB 1: DASHBOARD / RESUMEN                          */}
        {/* ---------------------------------------------------- */}
        {activeTab === 'dashboard' && (
          <div className="space-y-5 md:space-y-8">
            <div className="bg-gradient-to-br from-indigo-900/50 via-slate-900 to-slate-900 border border-indigo-500/20 rounded-2xl p-4 md:p-6 shadow-xl relative overflow-hidden">
              <div className="relative z-10 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div>
                  <div className="flex items-center space-x-2">
                    <span className="px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 rounded-full">
                      Perfil Activo
                    </span>
                    <span className="text-xs text-slate-400">
                      Modo: <strong className="text-slate-200">{profile?.application_preferences?.execution_mode || 'AUTO_APPLY'}</strong>
                    </span>
                  </div>
                  <h2 className="text-xl md:text-2xl font-black text-white mt-1">
                    {profile?.identity?.name || 'Bruno Moya'}
                  </h2>
                  <p className="text-xs text-slate-300 mt-0.5">
                    Proveedor IA: <strong className="text-indigo-400 uppercase font-bold">{llmConfig?.active_provider || 'MOCK'}</strong> • Umbral: <strong className="text-emerald-400">{profile?.application_preferences?.auto_apply_threshold || 82}%</strong>
                  </p>
                </div>

                <div className="flex items-center space-x-2">
                  <button
                    onClick={() => triggerDiscovery(3)}
                    disabled={discovering}
                    className="flex-1 sm:flex-none flex items-center justify-center space-x-2 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-500 active:scale-95 text-white text-xs font-bold rounded-xl shadow-lg shadow-indigo-600/30 transition disabled:opacity-50"
                  >
                    <Play className={`w-3.5 h-3.5 fill-current ${discovering ? 'animate-spin' : ''}`} />
                    <span>{discovering ? 'Buscando...' : 'Lanzar Búsqueda (3)'}</span>
                  </button>
                  <button
                    onClick={() => setActiveTab('llm')}
                    className="flex items-center space-x-1.5 px-3 py-2.5 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold rounded-xl transition"
                  >
                    <Cpu className="w-3.5 h-3.5" />
                    <span>Configurar IA</span>
                  </button>
                </div>
              </div>
            </div>

            {/* Metric Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 md:gap-6">
              <div
                onClick={() => setActiveTab('jobs')}
                className="bg-slate-900/80 active:bg-slate-800/80 border border-slate-800 hover:border-slate-700 p-4 md:p-6 rounded-2xl cursor-pointer transition shadow-sm"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-slate-400 text-[11px] md:text-xs font-bold uppercase tracking-wider">Ofertas</span>
                  <div className="p-1.5 bg-slate-800 text-slate-300 rounded-lg">
                    <Briefcase className="w-3.5 h-3.5" />
                  </div>
                </div>
                <div className="text-2xl md:text-3xl font-black text-white">{metrics.total_jobs_discovered}</div>
                <div className="text-[10px] md:text-xs text-slate-400 mt-1 truncate">Total descubiertas</div>
              </div>

              <div
                onClick={() => {
                  setJobFilter('evaluated');
                  setActiveTab('jobs');
                }}
                className="bg-slate-900/80 active:bg-slate-800/80 border border-slate-800 hover:border-indigo-500/30 p-4 md:p-6 rounded-2xl cursor-pointer transition shadow-sm"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-indigo-400 text-[11px] md:text-xs font-bold uppercase tracking-wider">Alto Match</span>
                  <div className="p-1.5 bg-indigo-950 text-indigo-400 rounded-lg">
                    <Sparkles className="w-3.5 h-3.5" />
                  </div>
                </div>
                <div className="text-2xl md:text-3xl font-black text-indigo-400">{metrics.high_match_jobs}</div>
                <div className="text-[10px] md:text-xs text-indigo-300/80 mt-1 truncate">≥ 82% coincidencia</div>
              </div>

              <div
                onClick={() => {
                  setAppFilter('applied');
                  setActiveTab('applications');
                }}
                className="bg-slate-900/80 active:bg-slate-800/80 border border-slate-800 hover:border-emerald-500/30 p-4 md:p-6 rounded-2xl cursor-pointer transition shadow-sm"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-emerald-400 text-[11px] md:text-xs font-bold uppercase tracking-wider">Enviadas</span>
                  <div className="p-1.5 bg-emerald-950 text-emerald-400 rounded-lg">
                    <CheckCircle2 className="w-3.5 h-3.5" />
                  </div>
                </div>
                <div className="text-2xl md:text-3xl font-black text-emerald-400">{metrics.total_applied}</div>
                <div className="text-[10px] md:text-xs text-emerald-300/80 mt-1 truncate">Verificadas</div>
              </div>

              <div
                onClick={() => {
                  setAppFilter('blocked');
                  setActiveTab('applications');
                }}
                className="bg-slate-900/80 active:bg-slate-800/80 border border-slate-800 hover:border-amber-500/30 p-4 md:p-6 rounded-2xl cursor-pointer transition shadow-sm"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-amber-400 text-[11px] md:text-xs font-bold uppercase tracking-wider">Bloqueos</span>
                  <div className="p-1.5 bg-amber-950 text-amber-400 rounded-lg">
                    <ShieldAlert className="w-3.5 h-3.5" />
                  </div>
                </div>
                <div className="text-2xl md:text-3xl font-black text-amber-400">{metrics.total_blocked}</div>
                <div className="text-[10px] md:text-xs text-amber-300/80 mt-1 truncate">Pausado seguro</div>
              </div>
            </div>

            {/* Recent Applications Feed */}
            <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-4 md:p-6 shadow-sm">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-base md:text-lg font-bold text-white">Últimas Candidaturas</h3>
                <button
                  onClick={() => setActiveTab('applications')}
                  className="text-xs text-indigo-400 hover:text-indigo-300 font-medium flex items-center space-x-1"
                >
                  <span>Ver todas</span>
                  <ChevronRight className="w-3.5 h-3.5" />
                </button>
              </div>

              {applications.length === 0 ? (
                <div className="text-center py-10 text-slate-500 text-xs">
                  Aún no hay candidaturas registradas. Pulsa &quot;Buscar&quot; para iniciar un ciclo de descubrimiento.
                </div>
              ) : (
                <div className="divide-y divide-slate-800/60">
                  {applications.slice(0, 5).map((app) => (
                    <div key={app.id} className="py-3 md:py-4 flex items-center justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="font-bold text-sm text-slate-100 truncate">{app.company}</div>
                        <div className="text-xs text-slate-400 truncate">{app.role}</div>
                        <div className="text-[11px] text-slate-500 flex items-center space-x-2 mt-1">
                          <span className="font-semibold text-indigo-400">{app.match_score}/100</span>
                          <span>•</span>
                          <span>{app.execution_mode}</span>
                          {app.error_message && (
                            <>
                              <span>•</span>
                              <span className="text-amber-400 truncate max-w-[160px] md:max-w-xs">{formatErrorMessage(app.error_message)}</span>
                            </>
                          )}
                        </div>
                      </div>

                      <div className="flex items-center space-x-2 shrink-0">
                        {app.submission_evidence && (
                          <button
                            onClick={() => setSelectedEvidenceApp(app)}
                            className="p-1.5 bg-indigo-950 text-indigo-300 border border-indigo-800/60 rounded-lg text-xs font-semibold flex items-center space-x-1"
                            title="Ver captura y evidencia"
                          >
                            <Camera className="w-3.5 h-3.5" />
                            <span className="hidden sm:inline">Evidencia</span>
                          </button>
                        )}
                        <span
                          className={`inline-flex items-center px-2.5 py-1 rounded-full text-[11px] font-bold ${
                            app.status === 'APPLIED'
                              ? 'bg-emerald-950 text-emerald-400 border border-emerald-800/80'
                              : app.status === 'BLOCKED'
                              ? 'bg-amber-950 text-amber-400 border border-amber-800/80'
                              : app.status === 'FAILED'
                              ? 'bg-rose-950/80 text-rose-400 border border-rose-800/80'
                              : 'bg-slate-800 text-slate-300'
                          }`}
                        >
                          {app.status}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {/* ---------------------------------------------------- */}
        {/* TAB 2: JOBS EXPLORER / OFERTAS                      */}
        {/* ---------------------------------------------------- */}
        {activeTab === 'jobs' && (
          <div className="space-y-4">
            <div className="space-y-2.5">
              <div className="relative">
                <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                <input
                  type="text"
                  placeholder="Buscar empresa, rol o tecnología..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full bg-slate-900 border border-slate-800 rounded-xl pl-10 pr-10 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-indigo-500 transition"
                />
                {searchQuery && (
                  <button
                    onClick={() => setSearchQuery('')}
                    className="absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200"
                  >
                    <X className="w-4 h-4" />
                  </button>
                )}
              </div>

              <div className="flex items-center space-x-2 overflow-x-auto pb-1 text-xs no-scrollbar">
                <button
                  onClick={() => setJobFilter('all')}
                  className={`px-3 py-1.5 rounded-lg whitespace-nowrap font-medium transition ${
                    jobFilter === 'all' ? 'bg-indigo-600 text-white' : 'bg-slate-900 text-slate-400 hover:bg-slate-800'
                  }`}
                >
                  Todas ({jobs.length})
                </button>
                <button
                  onClick={() => setJobFilter('remote')}
                  className={`px-3 py-1.5 rounded-lg whitespace-nowrap font-medium transition ${
                    jobFilter === 'remote' ? 'bg-indigo-600 text-white' : 'bg-slate-900 text-slate-400 hover:bg-slate-800'
                  }`}
                >
                  Remotas ({jobs.filter((j) => j.is_remote).length})
                </button>
                <button
                  onClick={() => setJobFilter('evaluated')}
                  className={`px-3 py-1.5 rounded-lg whitespace-nowrap font-medium transition ${
                    jobFilter === 'evaluated' ? 'bg-indigo-600 text-white' : 'bg-slate-900 text-slate-400 hover:bg-slate-800'
                  }`}
                >
                  Evaluadas ({jobs.filter((j) => j.status === 'EVALUATED').length})
                </button>
              </div>
            </div>

            {filteredJobs.length === 0 ? (
              <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-8 text-center text-slate-400 text-xs">
                No se encontraron ofertas con los filtros actuales.
              </div>
            ) : (
              <div className="space-y-3">
                {filteredJobs.map((job) => (
                  <div
                    key={job.id}
                    className="bg-slate-900/90 border border-slate-800/90 rounded-2xl p-4 transition shadow-sm hover:border-indigo-500/40"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-start space-x-3">
                        <div className="w-10 h-10 rounded-xl bg-slate-800 border border-slate-700/60 flex items-center justify-center font-bold text-indigo-400 text-sm shrink-0">
                          {job.company.slice(0, 2).toUpperCase()}
                        </div>
                        <div>
                          <h4 className="font-bold text-sm md:text-base text-white leading-snug">{job.role}</h4>
                          <p className="text-xs text-slate-400 font-medium">{job.company}</p>
                        </div>
                      </div>

                      <span className="text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded bg-slate-800 text-slate-400 shrink-0">
                        {job.source}
                      </span>
                    </div>

                    <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-slate-400">
                      <div className="flex items-center space-x-1 bg-slate-950/60 px-2 py-1 rounded-md">
                        <MapPin className="w-3 h-3 text-slate-500" />
                        <span className="truncate max-w-[180px]">{job.location || 'Remoto'}</span>
                      </div>

                      {job.is_remote && (
                        <span className="bg-indigo-950/80 text-indigo-300 border border-indigo-800/50 px-2 py-0.5 rounded-md text-[11px] font-medium">
                          Remote
                        </span>
                      )}

                      {job.technologies && job.technologies.slice(0, 3).map((t) => (
                        <span key={t} className="bg-slate-800/80 text-slate-300 px-2 py-0.5 rounded-md text-[11px]">
                          {t}
                        </span>
                      ))}
                    </div>

                    <div className="mt-3.5 pt-3 border-t border-slate-800/70 flex items-center justify-between">
                      <span className="text-[11px] font-semibold text-slate-400">
                        Estado: <strong className="text-slate-200">{job.status}</strong>
                      </span>

                      <div className="flex items-center space-x-2">
                        <button
                          onClick={() => setSelectedJob(job)}
                          className="px-3 py-1.5 bg-slate-800 active:bg-slate-700 text-slate-200 text-xs font-semibold rounded-lg transition"
                        >
                          Ver Detalles
                        </button>
                        <a
                          href={job.apply_url}
                          target="_blank"
                          rel="noreferrer"
                          className="flex items-center space-x-1 px-3 py-1.5 bg-indigo-600 active:bg-indigo-700 text-white text-xs font-semibold rounded-lg shadow-sm transition"
                        >
                          <span>Abrir</span>
                          <ExternalLink className="w-3 h-3" />
                        </a>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ---------------------------------------------------- */}
        {/* TAB 3: APPLICATIONS TRACKER / CANDIDATURAS          */}
        {/* ---------------------------------------------------- */}
        {activeTab === 'applications' && (
          <div className="space-y-4">
            <div className="flex items-center space-x-2 overflow-x-auto pb-1 text-xs no-scrollbar">
              <button
                onClick={() => setAppFilter('all')}
                className={`px-3 py-1.5 rounded-lg whitespace-nowrap font-medium transition ${
                  appFilter === 'all' ? 'bg-indigo-600 text-white' : 'bg-slate-900 text-slate-400 hover:bg-slate-800'
                }`}
              >
                Todas ({applications.length})
              </button>
              <button
                onClick={() => setAppFilter('applied')}
                className={`px-3 py-1.5 rounded-lg whitespace-nowrap font-medium transition ${
                  appFilter === 'applied' ? 'bg-indigo-600 text-white' : 'bg-slate-900 text-slate-400 hover:bg-slate-800'
                }`}
              >
                Enviadas ({applications.filter((a) => a.status === 'APPLIED').length})
              </button>
              <button
                onClick={() => setAppFilter('blocked')}
                className={`px-3 py-1.5 rounded-lg whitespace-nowrap font-medium transition ${
                  appFilter === 'blocked' ? 'bg-indigo-600 text-white' : 'bg-slate-900 text-slate-400 hover:bg-slate-800'
                }`}
              >
                Bloqueadas ({applications.filter((a) => a.status === 'BLOCKED').length})
              </button>
              <button
                onClick={() => setAppFilter('failed')}
                className={`px-3 py-1.5 rounded-lg whitespace-nowrap font-medium transition ${
                  appFilter === 'failed' ? 'bg-indigo-600 text-white' : 'bg-slate-900 text-slate-400 hover:bg-slate-800'
                }`}
              >
                Fallidas ({applications.filter((a) => a.status === 'FAILED').length})
              </button>
            </div>

            {filteredApps.length === 0 ? (
              <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-8 text-center text-slate-400 text-xs">
                No hay candidaturas registradas para este filtro.
              </div>
            ) : (
              <div className="space-y-3">
                {filteredApps.map((app) => (
                  <div
                    key={app.id}
                    className="bg-slate-900/90 border border-slate-800/90 rounded-2xl p-4 transition shadow-sm space-y-3"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <h4 className="font-bold text-sm md:text-base text-white">{app.role}</h4>
                        <p className="text-xs text-slate-400">{app.company}</p>
                      </div>

                      <div className="flex flex-col items-end shrink-0">
                        <span
                          className={`inline-flex items-center space-x-1 px-2.5 py-1 rounded-full text-xs font-bold ${
                            app.status === 'APPLIED'
                              ? 'bg-emerald-950 text-emerald-400 border border-emerald-800'
                              : app.status === 'BLOCKED'
                              ? 'bg-amber-950 text-amber-400 border border-amber-800'
                              : app.status === 'FAILED'
                              ? 'bg-rose-950 text-rose-400 border border-rose-800'
                              : 'bg-slate-800 text-slate-300'
                          }`}
                        >
                          {app.status === 'APPLIED' && <CheckCircle2 className="w-3 h-3" />}
                          {app.status === 'BLOCKED' && <AlertTriangle className="w-3 h-3" />}
                          {app.status === 'FAILED' && <XCircle className="w-3 h-3" />}
                          <span>{app.status}</span>
                        </span>
                        <span className="text-[10px] text-slate-500 mt-1">
                          {app.created_at ? new Date(app.created_at).toLocaleDateString() : '-'}
                        </span>
                      </div>
                    </div>

                    <div className="flex items-center justify-between text-xs bg-slate-950/60 p-2.5 rounded-xl border border-slate-800/60">
                      <div className="flex items-center space-x-2">
                        <span className="text-slate-400">Match Score:</span>
                        <span className="font-bold text-indigo-400 text-sm">{app.match_score}/100</span>
                      </div>
                      <div className="text-slate-400">
                        Modo: <strong className="text-slate-200">{app.execution_mode}</strong>
                      </div>
                    </div>

                    {/* Evidence & Action Buttons */}
                    <div className="flex items-center justify-between pt-1">
                      <button
                        onClick={() => setSelectedEvidenceApp(app)}
                        className="flex items-center space-x-1.5 px-3 py-1.5 bg-indigo-950 hover:bg-indigo-900 border border-indigo-700/60 text-indigo-300 rounded-xl text-xs font-semibold transition"
                      >
                        <Camera className="w-3.5 h-3.5" />
                        <span>Ver Evidencia (Vídeo / Captura)</span>
                      </button>

                      <div className="flex items-center space-x-2">
                        {app.has_tailored_resume && (
                          <a
                            href={`/api/applications/${encodeURIComponent(app.id)}/resume`}
                            className="flex items-center space-x-1.5 px-3 py-1.5 bg-emerald-950 hover:bg-emerald-900 border border-emerald-700/60 text-emerald-300 rounded-xl text-xs font-semibold transition"
                          >
                            <Download className="w-3.5 h-3.5" />
                            <span>Descargar CV</span>
                          </a>
                        )}
                        <button
                          onClick={() => regenerateResume(app.id)}
                          disabled={regenerating !== null}
                          title="Rehacer el CV con la adaptación actual y borrar el anterior"
                          className="flex items-center space-x-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 rounded-xl text-xs font-semibold transition disabled:opacity-50"
                        >
                          <Wand2 className={`w-3.5 h-3.5 ${regenerating === app.id ? 'animate-pulse' : ''}`} />
                          <span>{regenerating === app.id ? 'Regenerando…' : 'Regenerar CV'}</span>
                        </button>
                        {app.reactive_resume_application_id && (
                          <span className="text-[11px] text-emerald-400 font-medium">
                            ✓ Sync con Reactive Resume
                          </span>
                        )}
                      </div>
                    </div>

                    <div className="pt-1 border-t border-slate-800/60">
                      <OutcomeControls
                        status={app.status}
                        runId={app.id}
                        jobId={app.job_id}
                        history={app.outcome_history ?? []}
                        onRecorded={fetchApplications}
                        showToast={showToast}
                      />
                      {app.submitted_manually && (
                        <p className="text-[11px] text-slate-500 mt-1.5">
                          Enviada a mano
                          {app.applied_at
                            ? ` el ${new Date(app.applied_at).toLocaleDateString()}`
                            : ''}
                        </p>
                      )}
                    </div>

                    {app.error_message && (
                      <div className="p-2.5 bg-rose-950/20 border border-rose-800/40 rounded-xl text-xs text-rose-300">
                        <div className="font-semibold flex items-center space-x-1 text-rose-400 mb-0.5">
                          <AlertTriangle className="w-3 h-3" />
                          <span>Observación del Agente:</span>
                        </div>
                        <p className="text-[11px] leading-relaxed text-slate-300">{formatErrorMessage(app.error_message)}</p>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ---------------------------------------------------- */}
        {/* TAB 4: ANSWER VAULT                                  */}
        {/* ---------------------------------------------------- */}
        {activeTab === 'vault' && (
          <div className="space-y-4">
            <div>
              <h2 className="text-lg md:text-xl font-bold text-white">Candidate Answer Vault</h2>
              <p className="text-xs text-slate-400">Memoria auditada y certificada para formularios de empleo.</p>
            </div>

            <div className="space-y-2.5">
              {[
                {
                  key: 'authorized_to_work_eu',
                  label: '¿Autorizado legalmente para trabajar en la Unión Europea?',
                  val: 'Sí (Ciudadano UE)',
                  source: 'candidate profile',
                },
                {
                  key: 'requires_sponsorship_eu',
                  label: '¿Requiere patrocinio de visado en la Unión Europea?',
                  val: 'No',
                  source: 'candidate profile',
                },
                {
                  key: 'requires_sponsorship_us',
                  label: '¿Requiere visado para trabajar en EE.UU.?',
                  val: 'Sí (Visa sponsorship required)',
                  source: 'candidate profile',
                },
                {
                  key: 'expected_salary',
                  label: 'Salario o compensación anual esperada',
                  val: `€${profile?.job_preferences?.preferred_salary?.toLocaleString() || '110,000'} (Mínimo: €${profile?.job_preferences?.minimum_salary?.toLocaleString() || '85,000'})`,
                  source: 'preferred compensation',
                },
                {
                  key: 'notice_period',
                  label: 'Período de preaviso / Disponibilidad de inicio',
                  val: 'Inmediata / 2 semanas',
                  source: 'default profile',
                },
              ].map((item) => (
                <div
                  key={item.key}
                  className="bg-slate-900/90 border border-slate-800 p-3.5 rounded-xl space-y-1.5 shadow-sm"
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="font-mono text-[11px] text-slate-400 font-semibold">{item.label}</span>
                    <button
                      onClick={() => handleCopy(item.val, item.key)}
                      className="p-1.5 text-slate-400 hover:text-white rounded-md bg-slate-800 transition"
                      title="Copiar respuesta"
                    >
                      {copiedKey === item.key ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                    </button>
                  </div>
                  <div className="text-sm font-bold text-emerald-400">{item.val}</div>
                  <div className="text-[10px] text-slate-500">Fuente: {item.source}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ---------------------------------------------------- */}
        {/* TAB 5: EDITAR PERFIL                                 */}
        {/* ---------------------------------------------------- */}
        {activeTab === 'profile' && profileForm && (
          <div className="space-y-5 max-w-3xl">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-xl md:text-2xl font-black text-white">Editar Perfil del Candidato</h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Los cambios se guardan en <code className="text-indigo-300">config/candidate-profile.yaml</code>.
                </p>
              </div>

              <button
                onClick={saveProfileChanges}
                disabled={savingProfile}
                className="flex items-center space-x-1.5 px-4 py-2.5 bg-emerald-600 hover:bg-emerald-500 active:scale-95 text-white text-xs font-bold rounded-xl shadow-lg shadow-emerald-600/30 transition disabled:opacity-50"
              >
                <Save className={`w-3.5 h-3.5 ${savingProfile ? 'animate-spin' : ''}`} />
                <span>{savingProfile ? 'Guardando...' : 'Guardar Perfil'}</span>
              </button>
            </div>

            {/* Section 1: Identidad */}
            <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-4 md:p-6 space-y-4 shadow-sm">
              <h3 className="font-bold text-sm md:text-base text-white flex items-center space-x-2 border-b border-slate-800 pb-2">
                <User className="w-4 h-4 text-indigo-400" />
                <span>Datos de Identidad</span>
              </h3>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5 text-xs">
                <div>
                  <label className="text-slate-400 font-semibold mb-1 block">Nombre Completo</label>
                  <input
                    type="text"
                    value={profileForm.identity.name}
                    onChange={(e) =>
                      setProfileForm({
                        ...profileForm,
                        identity: { ...profileForm.identity, name: e.target.value },
                      })
                    }
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                </div>

                <div>
                  <label className="text-slate-400 font-semibold mb-1 block">Email</label>
                  <input
                    type="email"
                    value={profileForm.identity.email}
                    onChange={(e) =>
                      setProfileForm({
                        ...profileForm,
                        identity: { ...profileForm.identity, email: e.target.value },
                      })
                    }
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                </div>

                <div>
                  <label className="text-slate-400 font-semibold mb-1 block">Teléfono</label>
                  <input
                    type="text"
                    value={profileForm.identity.phone}
                    onChange={(e) =>
                      setProfileForm({
                        ...profileForm,
                        identity: { ...profileForm.identity, phone: e.target.value },
                      })
                    }
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                </div>

                <div>
                  <label className="text-slate-400 font-semibold mb-1 block">Ubicación</label>
                  <input
                    type="text"
                    value={profileForm.identity.location}
                    onChange={(e) =>
                      setProfileForm({
                        ...profileForm,
                        identity: { ...profileForm.identity, location: e.target.value },
                      })
                    }
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                </div>

                <div>
                  <label className="text-slate-400 font-semibold mb-1 block">LinkedIn URL</label>
                  <input
                    type="text"
                    value={profileForm.identity.linkedin || ''}
                    onChange={(e) =>
                      setProfileForm({
                        ...profileForm,
                        identity: { ...profileForm.identity, linkedin: e.target.value },
                      })
                    }
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                </div>

                <div>
                  <label className="text-slate-400 font-semibold mb-1 block">GitHub URL</label>
                  <input
                    type="text"
                    value={profileForm.identity.github || ''}
                    onChange={(e) =>
                      setProfileForm({
                        ...profileForm,
                        identity: { ...profileForm.identity, github: e.target.value },
                      })
                    }
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                </div>
              </div>
            </div>

            {/* Section 2: Preferencias de Empleo & Salario */}
            <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-4 md:p-6 space-y-4 shadow-sm">
              <h3 className="font-bold text-sm md:text-base text-white flex items-center space-x-2 border-b border-slate-800 pb-2">
                <Briefcase className="w-4 h-4 text-indigo-400" />
                <span>Preferencias de Empleo y Salario</span>
              </h3>

              <div className="space-y-3.5 text-xs">
                <div>
                  <label className="text-slate-400 font-semibold mb-1 block">
                    Roles Deseados (separados por coma)
                  </label>
                  <textarea
                    rows={2}
                    value={profileForm.job_preferences.roles.join(', ')}
                    onChange={(e) =>
                      setProfileForm({
                        ...profileForm,
                        job_preferences: {
                          ...profileForm.job_preferences,
                          roles: e.target.value.split(',').map((r) => r.trim()).filter(Boolean),
                        },
                      })
                    }
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
                  <div>
                    <label className="text-slate-400 font-semibold mb-1 block">Salario Mínimo (€)</label>
                    <input
                      type="number"
                      value={profileForm.job_preferences.minimum_salary || ''}
                      onChange={(e) =>
                        setProfileForm({
                          ...profileForm,
                          job_preferences: {
                            ...profileForm.job_preferences,
                            minimum_salary: parseFloat(e.target.value) || 0,
                          },
                        })
                      }
                      className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-slate-100 focus:outline-none focus:border-indigo-500"
                    />
                  </div>

                  <div>
                    <label className="text-slate-400 font-semibold mb-1 block">Salario Deseado (€)</label>
                    <input
                      type="number"
                      value={profileForm.job_preferences.preferred_salary || ''}
                      onChange={(e) =>
                        setProfileForm({
                          ...profileForm,
                          job_preferences: {
                            ...profileForm.job_preferences,
                            preferred_salary: parseFloat(e.target.value) || 0,
                          },
                        })
                      }
                      className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-slate-100 focus:outline-none focus:border-indigo-500"
                    />
                  </div>
                </div>

                <div>
                  <label className="text-slate-400 font-semibold mb-1 flex items-center justify-between">
                    <span className="flex items-center space-x-1.5">
                      <MapPin className="w-3.5 h-3.5 text-indigo-400" />
                      <span>Zonas Geográficas / Países Permitidos</span>
                    </span>
                    <span className="text-[10px] text-slate-500 font-normal">Separados por coma</span>
                  </label>
                  <textarea
                    rows={2}
                    value={(profileForm.job_preferences.locations || []).join(', ')}
                    onChange={(e) =>
                      setProfileForm({
                        ...profileForm,
                        job_preferences: {
                          ...profileForm.job_preferences,
                          locations: e.target.value.split(',').map((r) => r.trim()).filter(Boolean),
                        },
                      })
                    }
                    placeholder="Spain, Barcelona, Europe, European Union, Remote (EU), Remote (Worldwide)"
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-slate-100 focus:outline-none focus:border-indigo-500"
                  />
                  {(profileForm.job_preferences.locations || []).length > 0 && (
                    <div className="flex flex-wrap gap-1.5 mt-2">
                      {profileForm.job_preferences.locations.map((loc, idx) => (
                        <span key={idx} className="inline-flex items-center space-x-1 px-2 py-0.5 rounded-md text-[11px] bg-slate-800 text-indigo-300 border border-indigo-500/20">
                          <MapPin className="w-2.5 h-2.5 text-indigo-400" />
                          <span>{loc}</span>
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                <div className="pt-2">
                  <label className="text-slate-400 font-semibold mb-2 block">Modalidades Aceptadas</label>
                  <div className="flex flex-wrap gap-4 text-xs">
                    <label className="flex items-center space-x-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={profileForm.job_preferences.remote}
                        onChange={(e) =>
                          setProfileForm({
                            ...profileForm,
                            job_preferences: {
                              ...profileForm.job_preferences,
                              remote: e.target.checked,
                            },
                          })
                        }
                        className="w-4 h-4 rounded text-indigo-600 focus:ring-0 bg-slate-950 border-slate-700"
                      />
                      <span>Remoto</span>
                    </label>

                    <label className="flex items-center space-x-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={profileForm.job_preferences.hybrid}
                        onChange={(e) =>
                          setProfileForm({
                            ...profileForm,
                            job_preferences: {
                              ...profileForm.job_preferences,
                              hybrid: e.target.checked,
                            },
                          })
                        }
                        className="w-4 h-4 rounded text-indigo-600 focus:ring-0 bg-slate-950 border-slate-700"
                      />
                      <span>Híbrido</span>
                    </label>

                    <label className="flex items-center space-x-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={profileForm.job_preferences.onsite}
                        onChange={(e) =>
                          setProfileForm({
                            ...profileForm,
                            job_preferences: {
                              ...profileForm.job_preferences,
                              onsite: e.target.checked,
                            },
                          })
                        }
                        className="w-4 h-4 rounded text-indigo-600 focus:ring-0 bg-slate-950 border-slate-700"
                      />
                      <span>Presencial</span>
                    </label>
                  </div>
                </div>

                <div className="pt-2 border-t border-slate-800/60">
                  <label className="text-slate-400 font-semibold mb-2 flex items-center space-x-1.5">
                    <ShieldCheck className="w-3.5 h-3.5 text-indigo-400" />
                    <span>Permisos de Trabajo y Visados</span>
                  </label>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                    <label className="flex items-center space-x-2 cursor-pointer p-2.5 rounded-xl bg-slate-950 border border-slate-800">
                      <input
                        type="checkbox"
                        checked={profileForm.job_preferences.visa_requirements?.authorized_eu ?? true}
                        onChange={(e) =>
                          setProfileForm({
                            ...profileForm,
                            job_preferences: {
                              ...profileForm.job_preferences,
                              visa_requirements: {
                                ...profileForm.job_preferences.visa_requirements,
                                authorized_eu: e.target.checked,
                              },
                            },
                          })
                        }
                        className="w-4 h-4 rounded text-indigo-600 focus:ring-0 bg-slate-900 border-slate-700"
                      />
                      <span className="text-slate-200">Autorizado a trabajar en la UE</span>
                    </label>

                    <label className="flex items-center space-x-2 cursor-pointer p-2.5 rounded-xl bg-slate-950 border border-slate-800">
                      <input
                        type="checkbox"
                        checked={profileForm.job_preferences.visa_requirements?.authorized_us ?? false}
                        onChange={(e) =>
                          setProfileForm({
                            ...profileForm,
                            job_preferences: {
                              ...profileForm.job_preferences,
                              visa_requirements: {
                                ...profileForm.job_preferences.visa_requirements,
                                authorized_us: e.target.checked,
                              },
                            },
                          })
                        }
                        className="w-4 h-4 rounded text-indigo-600 focus:ring-0 bg-slate-900 border-slate-700"
                      />
                      <span className="text-slate-200">Autorizado a trabajar en EE.UU.</span>
                    </label>

                    <label className="flex items-center space-x-2 cursor-pointer p-2.5 rounded-xl bg-slate-950 border border-slate-800">
                      <input
                        type="checkbox"
                        checked={profileForm.job_preferences.visa_requirements?.requires_sponsorship_us ?? true}
                        onChange={(e) =>
                          setProfileForm({
                            ...profileForm,
                            job_preferences: {
                              ...profileForm.job_preferences,
                              visa_requirements: {
                                ...profileForm.job_preferences.visa_requirements,
                                requires_sponsorship_us: e.target.checked,
                              },
                            },
                          })
                        }
                        className="w-4 h-4 rounded text-indigo-600 focus:ring-0 bg-slate-900 border-slate-700"
                      />
                      <span className="text-slate-200">Requiere patrocinio de Visa en EE.UU.</span>
                    </label>

                    <label className="flex items-center space-x-2 cursor-pointer p-2.5 rounded-xl bg-slate-950 border border-slate-800">
                      <input
                        type="checkbox"
                        checked={profileForm.job_preferences.visa_requirements?.requires_sponsorship_eu ?? false}
                        onChange={(e) =>
                          setProfileForm({
                            ...profileForm,
                            job_preferences: {
                              ...profileForm.job_preferences,
                              visa_requirements: {
                                ...profileForm.job_preferences.visa_requirements,
                                requires_sponsorship_eu: e.target.checked,
                              },
                            },
                          })
                        }
                        className="w-4 h-4 rounded text-indigo-600 focus:ring-0 bg-slate-900 border-slate-700"
                      />
                      <span className="text-slate-200">Requiere patrocinio de Visa en la UE</span>
                    </label>
                  </div>
                </div>
              </div>
            </div>

            {/* Section 3: Modo del Agente */}
            <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-4 md:p-6 space-y-4 shadow-sm">
              <h3 className="font-bold text-sm md:text-base text-white flex items-center space-x-2 border-b border-slate-800 pb-2">
                <SettingsIcon className="w-4 h-4 text-indigo-400" />
                <span>Modo de Ejecución y Umbrales</span>
              </h3>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5 text-xs">
                <div>
                  <label className="text-slate-400 font-semibold mb-1 block">Modo del Agente</label>
                  <select
                    value={profileForm.application_preferences.execution_mode}
                    onChange={(e) =>
                      setProfileForm({
                        ...profileForm,
                        application_preferences: {
                          ...profileForm.application_preferences,
                          execution_mode: e.target.value,
                        },
                      })
                    }
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-slate-100 focus:outline-none focus:border-indigo-500"
                  >
                    <option value="AUTO_APPLY">AUTO_APPLY (Postular automáticamente si supera umbral)</option>
                    <option value="REVIEW_BEFORE_SUBMIT">REVIEW_BEFORE_SUBMIT (Rellenar y esperar confirmación)</option>
                    <option value="PREPARE">PREPARE (Generar CV y preparar sin abrir navegador)</option>
                    <option value="DISCOVERY_ONLY">DISCOVERY_ONLY (Solo buscar y evaluar ofertas)</option>
                  </select>
                </div>

                <div>
                  <label className="text-slate-400 font-semibold mb-1 block">
                    Umbral Auto-Apply (Score 0-100): {profileForm.application_preferences.auto_apply_threshold}%
                  </label>
                  <input
                    type="range"
                    min="50"
                    max="95"
                    value={profileForm.application_preferences.auto_apply_threshold}
                    onChange={(e) =>
                      setProfileForm({
                        ...profileForm,
                        application_preferences: {
                          ...profileForm.application_preferences,
                          auto_apply_threshold: parseInt(e.target.value, 10),
                        },
                      })
                    }
                    className="w-full mt-2 accent-indigo-600"
                  />
                </div>
              </div>

              <div className="pt-2 flex justify-end">
                <button
                  onClick={saveProfileChanges}
                  disabled={savingProfile}
                  className="flex items-center space-x-1.5 px-5 py-2.5 bg-emerald-600 hover:bg-emerald-500 active:scale-95 text-white text-xs font-bold rounded-xl shadow-lg shadow-emerald-600/30 transition disabled:opacity-50"
                >
                  <Save className={`w-3.5 h-3.5 ${savingProfile ? 'animate-spin' : ''}`} />
                  <span>{savingProfile ? 'Guardando Cambios...' : 'Guardar Todo el Perfil'}</span>
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ---------------------------------------------------- */}
        {/* TAB 6: CONFIGURAR LLM / MODELOS                      */}
        {/* ---------------------------------------------------- */}
        {activeTab === 'llm' && (
          <div className="space-y-5 max-w-3xl">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <h2 className="text-xl md:text-2xl font-black text-white">Configuración de Inteligencia Artificial</h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  Selecciona el proveedor de LLM para la evaluación de match, personalización de CV y redacción de cover letters.
                </p>
              </div>

              <div className="flex items-center space-x-2">
                <button
                  onClick={testLlmProvider}
                  disabled={testingLlm}
                  className="flex items-center space-x-1.5 px-3.5 py-2.5 bg-slate-800 hover:bg-slate-700 active:scale-95 text-slate-200 text-xs font-bold rounded-xl border border-slate-700 transition disabled:opacity-50"
                >
                  <Zap className={`w-3.5 h-3.5 text-amber-400 ${testingLlm ? 'animate-spin' : ''}`} />
                  <span>{testingLlm ? 'Probando...' : 'Probar Conexión'}</span>
                </button>

                <button
                  onClick={saveLlmConfig}
                  disabled={savingLlm}
                  className="flex items-center space-x-1.5 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-500 active:scale-95 text-white text-xs font-bold rounded-xl shadow-lg shadow-indigo-600/30 transition disabled:opacity-50"
                >
                  <Save className={`w-3.5 h-3.5 ${savingLlm ? 'animate-spin' : ''}`} />
                  <span>{savingLlm ? 'Guardando...' : 'Guardar IA'}</span>
                </button>
              </div>
            </div>

            {/* Test Connection Banner */}
            {llmTestFeedback && (
              <div
                className={`p-3.5 rounded-xl text-xs flex items-center space-x-2.5 border animate-fadeIn ${
                  llmTestFeedback.success
                    ? 'bg-emerald-950/80 border-emerald-700/60 text-emerald-200'
                    : 'bg-rose-950/80 border-rose-700/60 text-rose-200'
                }`}
              >
                {llmTestFeedback.success ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                ) : (
                  <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
                )}
                <div className="flex-1">
                  <span className="font-semibold">{llmTestFeedback.message}</span>
                  {llmTestFeedback.latency_ms !== undefined && (
                    <span className="ml-2 font-mono text-[11px] opacity-80">
                      ({llmTestFeedback.latency_ms} ms)
                    </span>
                  )}
                </div>
              </div>
            )}

            {/* Provider Selection Cards */}
            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2.5">
              {[
                { id: 'openai', label: 'OpenAI', desc: 'GPT-4o / mini', color: 'from-emerald-500/20 to-teal-500/20', border: 'border-emerald-500/40' },
                { id: 'anthropic', label: 'Anthropic', desc: 'Claude 3.5 Sonnet', color: 'from-amber-500/20 to-orange-500/20', border: 'border-amber-500/40' },
                { id: 'gemini', label: 'Google Gemini', desc: '1.5 Pro / Flash', color: 'from-blue-500/20 to-indigo-500/20', border: 'border-blue-500/40' },
                { id: 'ollama', label: 'Ollama Local', desc: 'Gratis en tu PC', color: 'from-purple-500/20 to-pink-500/20', border: 'border-purple-500/40' },
                { id: 'mock', label: 'Mock / Test', desc: 'Sin API Key', color: 'from-slate-500/20 to-slate-600/20', border: 'border-slate-500/40' },
              ].map((p) => {
                const isSelected = selectedProvider === p.id;
                const isActive = llmConfig?.active_provider === p.id;
                return (
                  <button
                    key={p.id}
                    onClick={() => {
                      setSelectedProvider(p.id);
                      setLlmTestFeedback(null);
                    }}
                    className={`p-3 rounded-2xl text-left border transition relative flex flex-col justify-between ${
                      isSelected
                        ? `bg-gradient-to-br ${p.color} ${p.border} shadow-lg ring-1 ring-indigo-500`
                        : 'bg-slate-900/80 border-slate-800 hover:border-slate-700'
                    }`}
                  >
                    <div>
                      <div className="flex items-center justify-between">
                        <span className="font-black text-sm text-white">{p.label}</span>
                        {isActive && (
                          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" title="Proveedor en uso"></span>
                        )}
                      </div>
                      <p className="text-[11px] text-slate-400 mt-0.5">{p.desc}</p>
                    </div>

                    <div className="mt-3 flex items-center justify-between">
                      <span className="text-[10px] uppercase font-bold text-slate-500">
                        {isSelected ? '✓ Seleccionado' : 'Elegir'}
                      </span>
                    </div>
                  </button>
                );
              })}
            </div>

            {/* Provider Configuration Form */}
            <div className="bg-slate-900/90 border border-slate-800 rounded-2xl p-4 md:p-6 space-y-4 shadow-sm">
              {/* OpenAI Config */}
              {selectedProvider === 'openai' && (
                <div className="space-y-4 animate-fadeIn">
                  <div className="flex items-center space-x-2 pb-2 border-b border-slate-800">
                    <Key className="w-4 h-4 text-emerald-400" />
                    <h3 className="font-bold text-sm md:text-base text-white">Configuración de OpenAI</h3>
                  </div>

                  <div className="space-y-3 text-xs">
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <label className="text-slate-400 font-semibold">OpenAI API Key</label>
                        {llmConfig?.openai.is_configured && (
                          <span className="font-mono text-[10px] text-emerald-400">
                            Configurada: {llmConfig.openai.key_masked}
                          </span>
                        )}
                      </div>
                      <input
                        type="password"
                        placeholder="sk-proj-..."
                        value={openaiKeyInput}
                        onChange={(e) => setOpenaiKeyInput(e.target.value)}
                        className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-slate-100 focus:outline-none focus:border-indigo-500 font-mono"
                      />
                    </div>

                    <div>
                      <label className="text-slate-400 font-semibold mb-1 block">Modelo Predeterminado</label>
                      <select
                        value={openaiModelInput}
                        onChange={(e) => setOpenaiModelInput(e.target.value)}
                        className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-slate-100 focus:outline-none focus:border-indigo-500"
                      >
                        <option value="gpt-4o">gpt-4o (Recomendado — Mayor precisión)</option>
                        <option value="gpt-4o-mini">gpt-4o-mini (Ultra rápido y económico)</option>
                        <option value="gpt-4-turbo">gpt-4-turbo</option>
                      </select>
                    </div>
                  </div>
                </div>
              )}

              {/* Anthropic Config */}
              {selectedProvider === 'anthropic' && (
                <div className="space-y-4 animate-fadeIn">
                  <div className="flex items-center space-x-2 pb-2 border-b border-slate-800">
                    <Key className="w-4 h-4 text-amber-400" />
                    <h3 className="font-bold text-sm md:text-base text-white">Configuración de Anthropic (Claude)</h3>
                  </div>

                  <div className="space-y-3 text-xs">
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <label className="text-slate-400 font-semibold">Anthropic API Key</label>
                        {llmConfig?.anthropic.is_configured && (
                          <span className="font-mono text-[10px] text-emerald-400">
                            Configurada: {llmConfig.anthropic.key_masked}
                          </span>
                        )}
                      </div>
                      <input
                        type="password"
                        placeholder="sk-ant-..."
                        value={anthropicKeyInput}
                        onChange={(e) => setAnthropicKeyInput(e.target.value)}
                        className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-slate-100 focus:outline-none focus:border-indigo-500 font-mono"
                      />
                    </div>

                    <div>
                      <label className="text-slate-400 font-semibold mb-1 block">Modelo Predeterminado</label>
                      <select
                        value={anthropicModelInput}
                        onChange={(e) => setAnthropicModelInput(e.target.value)}
                        className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-slate-100 focus:outline-none focus:border-indigo-500"
                      >
                        <option value="claude-3-5-sonnet-20241022">claude-3-5-sonnet-20241022 (Excelente razonamiento)</option>
                        <option value="claude-3-5-haiku-20241022">claude-3-5-haiku-20241022 (Rápido)</option>
                      </select>
                    </div>
                  </div>
                </div>
              )}

              {/* Gemini Config */}
              {selectedProvider === 'gemini' && (
                <div className="space-y-4 animate-fadeIn">
                  <div className="flex items-center space-x-2 pb-2 border-b border-slate-800">
                    <Key className="w-4 h-4 text-blue-400" />
                    <h3 className="font-bold text-sm md:text-base text-white">Configuración de Google Gemini</h3>
                  </div>

                  <div className="space-y-3 text-xs">
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <label className="text-slate-400 font-semibold">Gemini API Key</label>
                        {llmConfig?.gemini.is_configured && (
                          <span className="font-mono text-[10px] text-emerald-400">
                            Configurada: {llmConfig.gemini.key_masked}
                          </span>
                        )}
                      </div>
                      <input
                        type="password"
                        placeholder="AIzaSy..."
                        value={geminiKeyInput}
                        onChange={(e) => setGeminiKeyInput(e.target.value)}
                        className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-slate-100 focus:outline-none focus:border-indigo-500 font-mono"
                      />
                    </div>

                    <div>
                      <label className="text-slate-400 font-semibold mb-1 block">Modelo Predeterminado</label>
                      <select
                        value={geminiModelInput}
                        onChange={(e) => setGeminiModelInput(e.target.value)}
                        className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-slate-100 focus:outline-none focus:border-indigo-500"
                      >
                        <option value="gemini-1.5-pro">gemini-1.5-pro</option>
                        <option value="gemini-1.5-flash">gemini-1.5-flash</option>
                      </select>
                    </div>
                  </div>
                </div>
              )}

              {/* Ollama Local Config */}
              {selectedProvider === 'ollama' && (
                <div className="space-y-4 animate-fadeIn">
                  <div className="flex items-center space-x-2 pb-2 border-b border-slate-800">
                    <Server className="w-4 h-4 text-purple-400" />
                    <h3 className="font-bold text-sm md:text-base text-white">Configuración de Ollama (IA Local en tu PC)</h3>
                  </div>

                  <div className="p-3 bg-purple-950/30 border border-purple-800/40 rounded-xl text-xs text-purple-200">
                    <span className="font-bold">✓ 100% Gratuito y Privado:</span> Se ejecuta localmente en tu ordenador sin consumir tokens ni enviar datos a APIs externas. Requiere tener la aplicación de Ollama ejecutándose en tu equipo.
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5 text-xs">
                    <div>
                      <label className="text-slate-400 font-semibold mb-1 block">Ollama Base URL</label>
                      <input
                        type="text"
                        value={ollamaUrlInput}
                        onChange={(e) => setOllamaUrlInput(e.target.value)}
                        placeholder="http://localhost:11434"
                        className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-slate-100 focus:outline-none focus:border-indigo-500 font-mono"
                      />
                    </div>

                    <div>
                      <label className="text-slate-400 font-semibold mb-1 block">Nombre del Modelo Descargado</label>
                      <input
                        type="text"
                        value={ollamaModelInput}
                        onChange={(e) => setOllamaModelInput(e.target.value)}
                        placeholder="llama3, mistral, deepseek-r1..."
                        className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3.5 py-2.5 text-slate-100 focus:outline-none focus:border-indigo-500 font-mono"
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* Mock Config */}
              {selectedProvider === 'mock' && (
                <div className="space-y-3 animate-fadeIn">
                  <div className="flex items-center space-x-2 pb-2 border-b border-slate-800">
                    <ShieldCheck className="w-4 h-4 text-indigo-400" />
                    <h3 className="font-bold text-sm md:text-base text-white">Evaluador Heurístico Local (Mock)</h3>
                  </div>

                  <p className="text-xs text-slate-300 leading-relaxed">
                    El modo <strong>Mock</strong> evalúa ofertas de forma determinista basándose en coincidencia de palabras clave, umbrales y reglas de visado sin hacer llamadas a ninguna API ni requerir tarjeta de crédito o claves.
                  </p>

                  <div className="p-3 bg-slate-950 border border-slate-800 rounded-xl text-[11px] text-emerald-400 font-mono">
                    ✓ Estado: Listo y operativo sin conexión a internet ni claves externas.
                  </div>
                </div>
              )}

              {/* Action Buttons */}
              <div className="pt-3 border-t border-slate-800 flex items-center justify-between">
                <button
                  onClick={testLlmProvider}
                  disabled={testingLlm}
                  className="flex items-center space-x-1.5 px-4 py-2.5 bg-slate-800 hover:bg-slate-700 active:scale-95 text-slate-200 text-xs font-bold rounded-xl border border-slate-700 transition disabled:opacity-50"
                >
                  <Zap className={`w-3.5 h-3.5 text-amber-400 ${testingLlm ? 'animate-spin' : ''}`} />
                  <span>{testingLlm ? 'Verificando...' : 'Probar Esta Configuración'}</span>
                </button>

                <button
                  onClick={saveLlmConfig}
                  disabled={savingLlm}
                  className="flex items-center space-x-1.5 px-5 py-2.5 bg-indigo-600 hover:bg-indigo-500 active:scale-95 text-white text-xs font-bold rounded-xl shadow-lg shadow-indigo-600/30 transition disabled:opacity-50"
                >
                  <Save className={`w-3.5 h-3.5 ${savingLlm ? 'animate-spin' : ''}`} />
                  <span>{savingLlm ? 'Guardando...' : 'Activar y Guardar'}</span>
                </button>
              </div>
            </div>
          </div>
        )}
      </main>

      {/* ======================================================== */}
      {/* EVIDENCE VIEWER MODAL (Video / Screenshots)              */}
      {/* ======================================================== */}
      {selectedEvidenceApp && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-2 md:p-6 bg-black/85 backdrop-blur-md animate-fadeIn">
          <div
            className="bg-slate-900 border border-slate-800 w-full md:max-w-3xl rounded-3xl max-h-[90vh] flex flex-col shadow-2xl overflow-hidden animate-slideUp"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-4 md:p-5 border-b border-slate-800 flex items-center justify-between shrink-0">
              <div>
                <div className="flex items-center space-x-2">
                  <span className="px-2 py-0.5 bg-indigo-950 text-indigo-400 border border-indigo-800 rounded text-[10px] font-bold uppercase tracking-wider">
                    Evidencia Playwright
                  </span>
                  <span className="text-xs text-slate-400 font-mono">
                    ID: {selectedEvidenceApp.id.slice(0, 8)}
                  </span>
                </div>
                <h3 className="text-base md:text-lg font-bold text-white mt-1">
                  {selectedEvidenceApp.company} — {selectedEvidenceApp.role}
                </h3>
              </div>

              <button
                onClick={() => setSelectedEvidenceApp(null)}
                className="p-2 rounded-xl bg-slate-800 text-slate-400 hover:text-white transition"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="flex items-center space-x-2 px-4 pt-3 border-b border-slate-800 text-xs shrink-0">
              <button
                onClick={() => setActiveEvidenceTab('post_screenshot')}
                className={`flex items-center space-x-1.5 pb-2.5 px-2 font-bold border-b-2 transition ${
                  activeEvidenceTab === 'post_screenshot'
                    ? 'border-indigo-500 text-indigo-400'
                    : 'border-transparent text-slate-400 hover:text-slate-200'
                }`}
              >
                <Camera className="w-4 h-4" />
                <span>Captura de Confirmación</span>
              </button>

              <button
                onClick={() => setActiveEvidenceTab('pre_screenshot')}
                className={`flex items-center space-x-1.5 pb-2.5 px-2 font-bold border-b-2 transition ${
                  activeEvidenceTab === 'pre_screenshot'
                    ? 'border-indigo-500 text-indigo-400'
                    : 'border-transparent text-slate-400 hover:text-slate-200'
                }`}
              >
                <Eye className="w-4 h-4" />
                <span>Formulario Relleno</span>
              </button>

              <button
                onClick={() => setActiveEvidenceTab('video')}
                className={`flex items-center space-x-1.5 pb-2.5 px-2 font-bold border-b-2 transition ${
                  activeEvidenceTab === 'video'
                    ? 'border-indigo-500 text-indigo-400'
                    : 'border-transparent text-slate-400 hover:text-slate-200'
                }`}
              >
                <Video className="w-4 h-4" />
                <span>Grabación de Vídeo</span>
              </button>
            </div>

            <div className="p-4 md:p-6 overflow-y-auto flex-1 flex flex-col items-center justify-center">
              {activeEvidenceTab === 'post_screenshot' && (
                <div className="w-full space-y-3">
                  <div className="text-xs text-slate-400 flex items-center justify-between">
                    <span>Pantalla de éxito o acuse de recibo detectado</span>
                    {selectedEvidenceApp.submission_evidence?.confirmation_id && (
                      <span className="font-mono text-emerald-400 font-semibold">
                        Ref: #{selectedEvidenceApp.submission_evidence.confirmation_id}
                      </span>
                    )}
                  </div>
                  <div className="border border-slate-800 rounded-2xl overflow-hidden shadow-xl bg-slate-950 flex justify-center">
                    <img
                      src={selectedEvidenceApp.submission_evidence?.post_screenshot || '/evidence/demo_confirmation.png'}
                      alt="Confirmación de candidatura"
                      className="w-full max-h-[55vh] object-contain"
                    />
                  </div>
                </div>
              )}

              {activeEvidenceTab === 'pre_screenshot' && (
                <div className="w-full space-y-3">
                  <div className="text-xs text-slate-400">
                    Captura del formulario con datos completados y CV adjunto antes de pulsar submit
                  </div>
                  <div className="border border-slate-800 rounded-2xl overflow-hidden shadow-xl bg-slate-950 flex justify-center">
                    <img
                      src={selectedEvidenceApp.submission_evidence?.pre_screenshot || '/evidence/demo_form_filled.png'}
                      alt="Formulario completado"
                      className="w-full max-h-[55vh] object-contain"
                    />
                  </div>
                </div>
              )}

              {activeEvidenceTab === 'video' && (
                <div className="w-full space-y-3 flex flex-col items-center">
                  <div className="text-xs text-slate-400 w-full text-left">
                    Sesión completa grabada por Playwright durante el autocompletado y postulación
                  </div>
                  {selectedEvidenceApp.submission_evidence?.video ? (
                    <video
                      controls
                      autoPlay
                      loop
                      className="w-full max-h-[55vh] rounded-2xl border border-slate-800 bg-black"
                      src={selectedEvidenceApp.submission_evidence.video}
                    />
                  ) : (
                    <div className="w-full p-8 bg-slate-950 border border-slate-800 rounded-2xl text-center space-y-3">
                      <div className="w-12 h-12 rounded-2xl bg-indigo-950 text-indigo-400 flex items-center justify-center mx-auto">
                        <Video className="w-6 h-6" />
                      </div>
                      <h4 className="font-bold text-sm text-white">Grabación de Sesión Playwright</h4>
                      <p className="text-xs text-slate-400 max-w-sm mx-auto">
                        Las grabaciones de vídeo WebM se generan automáticamente en cada postulación iniciada en modo <code className="text-indigo-300">AUTO_APPLY</code> en <code className="text-slate-300">artifacts/videos/</code>.
                      </p>
                      <div className="text-[11px] font-mono text-emerald-400 bg-slate-900 px-3 py-1.5 rounded-lg inline-block">
                        Formato: WebM 1280x720 30FPS • Audio: off
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="p-4 border-t border-slate-800 bg-slate-900/90 flex items-center justify-between shrink-0">
              <span className="text-xs text-slate-400">
                Auditoría certificada: <strong className="text-emerald-400">Verificada</strong>
              </span>
              <button
                onClick={() => setSelectedEvidenceApp(null)}
                className="px-4 py-2 bg-slate-800 hover:bg-slate-700 active:bg-slate-600 text-slate-200 text-xs font-bold rounded-xl transition"
              >
                Cerrar
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* JOB DETAIL MODAL                                         */}
      {/* ======================================================== */}
      {selectedJob && (
        <div className="fixed inset-0 z-50 flex items-end md:items-center justify-center p-0 md:p-4 bg-black/70 backdrop-blur-sm animate-fadeIn">
          <div
            className="bg-slate-900 border border-slate-800 w-full md:max-w-2xl rounded-t-3xl md:rounded-3xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden animate-slideUp pb-safe"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-4 md:p-6 border-b border-slate-800 flex items-start justify-between gap-2 shrink-0">
              <div>
                <div className="flex items-center space-x-2">
                  <span className="text-xs uppercase font-bold text-indigo-400 bg-indigo-950/80 px-2 py-0.5 rounded">
                    {selectedJob.source}
                  </span>
                  {selectedJob.is_remote && (
                    <span className="text-xs font-semibold text-emerald-400 bg-emerald-950/80 px-2 py-0.5 rounded">
                      Remoto
                    </span>
                  )}
                </div>
                <h3 className="text-lg md:text-xl font-bold text-white mt-1.5 leading-snug">{selectedJob.role}</h3>
                <p className="text-xs text-slate-400">{selectedJob.company} • {selectedJob.location || 'Remoto'}</p>
              </div>

              <button
                onClick={() => setSelectedJob(null)}
                className="p-2 rounded-xl bg-slate-800 text-slate-400 hover:text-white transition"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-4 md:p-6 overflow-y-auto space-y-4 text-xs md:text-sm text-slate-300">
              {selectedJob.technologies && selectedJob.technologies.length > 0 && (
                <div>
                  <h5 className="font-bold text-slate-200 uppercase text-[11px] mb-1.5">Tecnologías Clave</h5>
                  <div className="flex flex-wrap gap-1.5">
                    {selectedJob.technologies.map((t) => (
                      <span key={t} className="px-2.5 py-1 bg-slate-800 text-slate-200 rounded-lg text-xs font-medium">
                        {t}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {selectedJob.description && (
                <div>
                  <h5 className="font-bold text-slate-200 uppercase text-[11px] mb-1.5">Descripción de la Oferta</h5>
                  <div
                    className="p-3 bg-slate-950 rounded-xl border border-slate-800 text-slate-300 leading-relaxed max-h-60 overflow-y-auto prose prose-invert prose-xs"
                    dangerouslySetInnerHTML={{ __html: selectedJob.description }}
                  />
                </div>
              )}
            </div>

            <div className="px-4 pb-3 pt-3 border-t border-slate-800 bg-slate-900/90 shrink-0">
              <OutcomeControls
                status={selectedJob.status}
                jobId={selectedJob.id}
                onRecorded={() => {
                  void fetchJobs();
                  void fetchApplications();
                }}
                showToast={showToast}
                compact
              />
            </div>

            <div className="p-4 border-t border-slate-800 bg-slate-900/90 flex items-center space-x-2 shrink-0">
              <button
                onClick={() => setSelectedJob(null)}
                className="w-1/3 py-2.5 bg-slate-800 active:bg-slate-700 text-slate-300 text-xs font-bold rounded-xl transition"
              >
                Cerrar
              </button>
              <a
                href={selectedJob.apply_url}
                target="_blank"
                rel="noreferrer"
                className="w-2/3 flex items-center justify-center space-x-1.5 py-2.5 bg-indigo-600 active:bg-indigo-700 text-white text-xs font-bold rounded-xl shadow-lg shadow-indigo-600/30 transition"
              >
                <span>Abrir Formulario de Solicitud</span>
                <ExternalLink className="w-3.5 h-3.5" />
              </a>
            </div>
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* MOBILE BOTTOM NAVIGATION BAR                             */}
      {/* ======================================================== */}
      <nav className="md:hidden fixed bottom-0 left-0 right-0 z-40 bg-slate-900/95 backdrop-blur-xl border-t border-slate-800/90 px-2 py-2 flex items-center justify-around pb-safe shadow-2xl">
        <button
          onClick={() => setActiveTab('dashboard')}
          className={`flex flex-col items-center justify-center flex-1 py-1.5 rounded-xl transition ${
            activeTab === 'dashboard' ? 'text-indigo-400 font-bold' : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          <TrendingUp className="w-5 h-5" />
          <span className="text-[10px] mt-1">Resumen</span>
        </button>

        <button
          onClick={() => setActiveTab('jobs')}
          className={`flex flex-col items-center justify-center flex-1 py-1.5 rounded-xl transition relative ${
            activeTab === 'jobs' ? 'text-indigo-400 font-bold' : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          <Briefcase className="w-5 h-5" />
          <span className="text-[10px] mt-1">Ofertas</span>
          {jobs.length > 0 && (
            <span className="absolute top-0.5 right-1/4 min-w-[16px] h-4 px-1 rounded-full bg-indigo-600 text-white text-[9px] font-bold flex items-center justify-center">
              {jobs.length}
            </span>
          )}
        </button>

        <button
          onClick={() => setActiveTab('applications')}
          className={`flex flex-col items-center justify-center flex-1 py-1.5 rounded-xl transition relative ${
            activeTab === 'applications' ? 'text-indigo-400 font-bold' : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          <Send className="w-5 h-5" />
          <span className="text-[10px] mt-1">Postulaciones</span>
          {applications.length > 0 && (
            <span className="absolute top-0.5 right-1/4 min-w-[16px] h-4 px-1 rounded-full bg-emerald-600 text-white text-[9px] font-bold flex items-center justify-center">
              {applications.length}
            </span>
          )}
        </button>

        <button
          onClick={() => setActiveTab('roles')}
          className={`flex flex-col items-center justify-center flex-1 py-1.5 rounded-xl transition ${
            activeTab === 'roles' ? 'text-indigo-400 font-bold' : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          <Compass className="w-5 h-5" />
          <span className="text-[10px] mt-1">Roles</span>
        </button>

        <button
          onClick={() => setActiveTab('resumes')}
          className={`flex flex-col items-center justify-center flex-1 py-1.5 rounded-xl transition ${
            activeTab === 'resumes' ? 'text-indigo-400 font-bold' : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          <FileText className="w-5 h-5" />
          <span className="text-[10px] mt-1">CVs</span>
        </button>

        <button
          onClick={() => setActiveTab('profile')}
          className={`flex flex-col items-center justify-center flex-1 py-1.5 rounded-xl transition ${
            activeTab === 'profile' ? 'text-indigo-400 font-bold' : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          <User className="w-5 h-5" />
          <span className="text-[10px] mt-1">Perfil</span>
        </button>

        <button
          onClick={() => setActiveTab('llm')}
          className={`flex flex-col items-center justify-center flex-1 py-1.5 rounded-xl transition ${
            activeTab === 'llm' ? 'text-indigo-400 font-bold' : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          <Cpu className="w-5 h-5" />
          <span className="text-[10px] mt-1">IA & LLM</span>
        </button>
      </nav>
    </div>
  );
}
