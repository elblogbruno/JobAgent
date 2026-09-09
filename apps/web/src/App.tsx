import { useState, useEffect } from 'react';
import {
  Briefcase,
  Send,
  Settings as SettingsIcon,
  HelpCircle,
  RefreshCw,
  ExternalLink,
  TrendingUp,
} from 'lucide-react';

interface Job {
  id: string;
  company: string;
  role: string;
  location: string;
  is_remote: boolean;
  source: string;
  status: string;
  apply_url: string;
  discovered_at: string;
  technologies: string[];
  salary: string;
}

interface Application {
  id: string;
  job_id: string;
  company: string;
  role: string;
  status: string;
  execution_mode: string;
  match_score: number;
  reactive_resume_application_id: string;
  created_at: string;
  error_message?: string;
}

interface SystemMetrics {
  total_jobs_discovered: number;
  high_match_jobs: number;
  total_applied: number;
  total_blocked: number;
  pending_questions: number;
}

export default function App() {
  const [activeTab, setActiveTab] = useState<'dashboard' | 'jobs' | 'applications' | 'vault' | 'settings'>('dashboard');
  const [metrics, setMetrics] = useState<SystemMetrics>({
    total_jobs_discovered: 0,
    high_match_jobs: 0,
    total_applied: 0,
    total_blocked: 0,
    pending_questions: 0,
  });
  const [jobs, setJobs] = useState<Job[]>([]);
  const [applications, setApplications] = useState<Application[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  const fetchMetrics = async () => {
    try {
      const res = await fetch('/api/system/metrics');
      if (res.ok) {
        const data = await res.json();
        setMetrics(data);
      }
    } catch {
      // Offline fallback
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
      // Offline fallback
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
      // Offline fallback
    }
  };

  const refreshAll = async () => {
    setLoading(true);
    await Promise.all([fetchMetrics(), fetchJobs(), fetchApplications()]);
    setLoading(false);
  };

  useEffect(() => {
    refreshAll();
  }, []);

  return (
    <div className="flex min-h-screen bg-slate-950 text-slate-100">
      {/* Sidebar Navigation */}
      <aside className="w-64 bg-slate-900 border-r border-slate-800 p-6 flex flex-col justify-between">
        <div>
          <div className="flex items-center space-x-3 mb-8">
            <div className="bg-indigo-600 p-2.5 rounded-xl shadow-lg shadow-indigo-600/30">
              <Briefcase className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight">Job Agent</h1>
              <p className="text-xs text-slate-400">Autonomous Assistant</p>
            </div>
          </div>

          <nav className="space-y-1">
            <button
              onClick={() => setActiveTab('dashboard')}
              className={`w-full flex items-center space-x-3 px-4 py-3 rounded-lg text-sm font-medium transition ${
                activeTab === 'dashboard' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              }`}
            >
              <TrendingUp className="w-5 h-5" />
              <span>Dashboard</span>
            </button>

            <button
              onClick={() => setActiveTab('jobs')}
              className={`w-full flex items-center space-x-3 px-4 py-3 rounded-lg text-sm font-medium transition ${
                activeTab === 'jobs' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              }`}
            >
              <Briefcase className="w-5 h-5" />
              <span>Jobs Explorer</span>
            </button>

            <button
              onClick={() => setActiveTab('applications')}
              className={`w-full flex items-center space-x-3 px-4 py-3 rounded-lg text-sm font-medium transition ${
                activeTab === 'applications' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              }`}
            >
              <Send className="w-5 h-5" />
              <span>Applications</span>
            </button>

            <button
              onClick={() => setActiveTab('vault')}
              className={`w-full flex items-center space-x-3 px-4 py-3 rounded-lg text-sm font-medium transition ${
                activeTab === 'vault' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              }`}
            >
              <HelpCircle className="w-5 h-5" />
              <span>Answer Vault</span>
            </button>

            <button
              onClick={() => setActiveTab('settings')}
              className={`w-full flex items-center space-x-3 px-4 py-3 rounded-lg text-sm font-medium transition ${
                activeTab === 'settings' ? 'bg-indigo-600 text-white' : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              }`}
            >
              <SettingsIcon className="w-5 h-5" />
              <span>Settings</span>
            </button>
          </nav>
        </div>

        <div className="border-t border-slate-800 pt-4">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span className="flex items-center space-x-1">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
              <span>Agent Online</span>
            </span>
            <button
              onClick={refreshAll}
              disabled={loading}
              className="p-1.5 hover:bg-slate-800 rounded-md transition"
              title="Refresh Data"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 p-8 overflow-y-auto">
        {activeTab === 'dashboard' && (
          <div className="space-y-8">
            <div>
              <h2 className="text-2xl font-bold">Pipeline Overview</h2>
              <p className="text-slate-400 text-sm">Real-time stats from autonomous discovery and application cycles.</p>
            </div>

            {/* Metric Cards */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
              <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl">
                <div className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-2">Discovered Jobs</div>
                <div className="text-3xl font-extrabold text-white">{metrics.total_jobs_discovered}</div>
                <div className="text-xs text-emerald-400 mt-2">Ingested across all ATS sources</div>
              </div>

              <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl">
                <div className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-2">High Match Jobs</div>
                <div className="text-3xl font-extrabold text-indigo-400">{metrics.high_match_jobs}</div>
                <div className="text-xs text-slate-400 mt-2">Score &gt;= 82 threshold</div>
              </div>

              <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl">
                <div className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-2">Submitted Applications</div>
                <div className="text-3xl font-extrabold text-emerald-400">{metrics.total_applied}</div>
                <div className="text-xs text-emerald-400 mt-2">Verified with confirmation evidence</div>
              </div>

              <div className="bg-slate-900 border border-slate-800 p-6 rounded-2xl">
                <div className="text-slate-400 text-xs font-semibold uppercase tracking-wider mb-2">Blocked / Captcha</div>
                <div className="text-3xl font-extrabold text-amber-400">{metrics.total_blocked}</div>
                <div className="text-xs text-slate-400 mt-2">Safely halted without evasion</div>
              </div>
            </div>

            {/* Recent Applications Feed */}
            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
              <h3 className="text-lg font-bold mb-4">Recent Application Runs</h3>
              {applications.length === 0 ? (
                <div className="text-center py-12 text-slate-500 text-sm">No applications recorded yet. Run a discovery cycle to begin.</div>
              ) : (
                <div className="divide-y divide-slate-800">
                  {applications.slice(0, 5).map((app) => (
                    <div key={app.id} className="py-4 flex items-center justify-between">
                      <div>
                        <div className="font-semibold">{app.company} — {app.role}</div>
                        <div className="text-xs text-slate-400 flex items-center space-x-2 mt-1">
                          <span>Mode: {app.execution_mode}</span>
                          <span>•</span>
                          <span>Score: {app.match_score}/100</span>
                        </div>
                      </div>
                      <span className={`px-3 py-1 rounded-full text-xs font-medium ${
                        app.status === 'APPLIED' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' :
                        app.status === 'BLOCKED' ? 'bg-amber-950 text-amber-400 border border-amber-800' :
                        'bg-slate-800 text-slate-300'
                      }`}>
                        {app.status}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'jobs' && (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-2xl font-bold">Discovered Jobs</h2>
                <p className="text-slate-400 text-sm">Normalized canonical postings evaluated by Job Agent.</p>
              </div>
              <input
                type="text"
                placeholder="Search company, role or tech..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="bg-slate-900 border border-slate-800 px-4 py-2 rounded-lg text-sm w-72 focus:outline-none focus:border-indigo-500"
              />
            </div>

            <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
              <table className="w-full text-left border-collapse text-sm">
                <thead>
                  <tr className="border-b border-slate-800 bg-slate-900/50 text-slate-400 text-xs uppercase">
                    <th className="p-4">Company</th>
                    <th className="p-4">Role</th>
                    <th className="p-4">Location</th>
                    <th className="p-4">Source</th>
                    <th className="p-4">Status</th>
                    <th className="p-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {jobs.filter(j => j.company.toLowerCase().includes(searchQuery.toLowerCase()) || j.role.toLowerCase().includes(searchQuery.toLowerCase())).map((job) => (
                    <tr key={job.id} className="hover:bg-slate-800/40 transition">
                      <td className="p-4 font-semibold">{job.company}</td>
                      <td className="p-4">{job.role}</td>
                      <td className="p-4 text-slate-400">
                        {job.location || 'Remote'}
                        {job.is_remote && <span className="ml-2 text-xs bg-indigo-950 text-indigo-400 px-2 py-0.5 rounded">Remote</span>}
                      </td>
                      <td className="p-4 text-xs uppercase tracking-wider text-slate-400">{job.source}</td>
                      <td className="p-4">
                        <span className="text-xs px-2.5 py-1 rounded-full bg-slate-800 text-slate-300">
                          {job.status}
                        </span>
                      </td>
                      <td className="p-4 text-right">
                        <a
                          href={job.apply_url}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center text-xs text-indigo-400 hover:text-indigo-300 space-x-1"
                        >
                          <span>Open</span>
                          <ExternalLink className="w-3.5 h-3.5" />
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {activeTab === 'applications' && (
          <div className="space-y-6">
            <div>
              <h2 className="text-2xl font-bold">Applications Tracker</h2>
              <p className="text-slate-400 text-sm">Track tailored resumes, submissions, and status changes synchronized with Reactive Resume.</p>
            </div>

            <div className="bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden">
              <table className="w-full text-left border-collapse text-sm">
                <thead>
                  <tr className="border-b border-slate-800 bg-slate-900/50 text-slate-400 text-xs uppercase">
                    <th className="p-4">Company & Role</th>
                    <th className="p-4">Match Score</th>
                    <th className="p-4">Status</th>
                    <th className="p-4">Mode</th>
                    <th className="p-4">Date</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {applications.map((app) => (
                    <tr key={app.id} className="hover:bg-slate-800/40 transition">
                      <td className="p-4">
                        <div className="font-semibold">{app.company}</div>
                        <div className="text-xs text-slate-400">{app.role}</div>
                      </td>
                      <td className="p-4">
                        <span className="font-bold text-indigo-400">{app.match_score}/100</span>
                      </td>
                      <td className="p-4">
                        <span className={`px-2.5 py-1 rounded-full text-xs font-semibold ${
                          app.status === 'APPLIED' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800' :
                          app.status === 'BLOCKED' ? 'bg-amber-950 text-amber-400 border border-amber-800' :
                          'bg-slate-800 text-slate-300'
                        }`}>
                          {app.status}
                        </span>
                      </td>
                      <td className="p-4 text-xs text-slate-400">{app.execution_mode}</td>
                      <td className="p-4 text-xs text-slate-400">{app.created_at ? new Date(app.created_at).toLocaleDateString() : '-'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {activeTab === 'vault' && (
          <div className="space-y-6">
            <div>
              <h2 className="text-2xl font-bold">Candidate Answer Vault</h2>
              <p className="text-slate-400 text-sm">Auditable memory of verified answers to recurring job application questions.</p>
            </div>

            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="p-4 bg-slate-950 rounded-xl border border-slate-800">
                  <div className="text-xs text-slate-400 font-mono">authorized_to_work_eu</div>
                  <div className="text-base font-bold text-emerald-400 mt-1">True</div>
                  <div className="text-xs text-slate-500 mt-1">Source: candidate profile</div>
                </div>

                <div className="p-4 bg-slate-950 rounded-xl border border-slate-800">
                  <div className="text-xs text-slate-400 font-mono">requires_sponsorship_eu</div>
                  <div className="text-base font-bold text-emerald-400 mt-1">False</div>
                  <div className="text-xs text-slate-500 mt-1">Source: candidate profile</div>
                </div>

                <div className="p-4 bg-slate-950 rounded-xl border border-slate-800">
                  <div className="text-xs text-slate-400 font-mono">expected_salary</div>
                  <div className="text-base font-bold text-indigo-400 mt-1">€110,000</div>
                  <div className="text-xs text-slate-500 mt-1">Source: preferred compensation</div>
                </div>

                <div className="p-4 bg-slate-950 rounded-xl border border-slate-800">
                  <div className="text-xs text-slate-400 font-mono">notice_period</div>
                  <div className="text-base font-bold text-slate-200 mt-1">Immediate / 2 weeks</div>
                  <div className="text-xs text-slate-500 mt-1">Source: default profile</div>
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'settings' && (
          <div className="space-y-6 max-w-2xl">
            <div>
              <h2 className="text-2xl font-bold">System Settings</h2>
              <p className="text-slate-400 text-sm">Configured via candidate-profile.yaml and environment variables.</p>
            </div>

            <div className="bg-slate-900 border border-slate-800 rounded-2xl p-6 space-y-4">
              <div>
                <label className="text-xs text-slate-400 uppercase font-semibold">Candidate Identity</label>
                <div className="font-semibold text-lg">Bruno Moya</div>
                <div className="text-sm text-slate-400">bruno.moya@example.com • Barcelona, Spain</div>
              </div>

              <div className="border-t border-slate-800 pt-4">
                <label className="text-xs text-slate-400 uppercase font-semibold">Execution Mode</label>
                <div className="text-sm font-semibold text-indigo-400 mt-1">AUTO_APPLY</div>
                <div className="text-xs text-slate-400 mt-1">Auto apply threshold: 82 • Prepare threshold: 65</div>
              </div>

              <div className="border-t border-slate-800 pt-4">
                <label className="text-xs text-slate-400 uppercase font-semibold">Active Integrations</label>
                <div className="flex items-center space-x-3 mt-2 text-xs">
                  <span className="px-3 py-1 bg-emerald-950 border border-emerald-800 text-emerald-400 rounded-full">Reactive Resume API</span>
                  <span className="px-3 py-1 bg-emerald-950 border border-emerald-800 text-emerald-400 rounded-full">Telegram Bot</span>
                  <span className="px-3 py-1 bg-indigo-950 border border-indigo-800 text-indigo-400 rounded-full">Playwright Browser</span>
                </div>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
