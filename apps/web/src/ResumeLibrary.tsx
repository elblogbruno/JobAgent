import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle,
  Check,
  Download,
  ExternalLink,
  FileText,
  LayoutGrid,
  List as ListIcon,
  Lock,
  RefreshCw,
  Search,
  Sparkles,
  Star,
  Trash2,
} from 'lucide-react';

interface ResumeRow {
  id: string;
  name: string;
  slug: string;
  tags: string[];
  locked: boolean;
  isPublic: boolean;
  isMaster: boolean;
  createdAt: string | null;
  updatedAt: string | null;
}

interface ResumeListResponse {
  count: number;
  masterResumeId: string;
  masterResumeName: string;
  masterResumeFound: boolean;
  resumes: ResumeRow[];
}

interface SectionSummary {
  key: string;
  name: string;
  items: number;
  visible: boolean;
}

interface ResumeDetail {
  id: string;
  name: string;
  basics: { name?: string; headline?: string; location?: string; email?: string };
  sections: SectionSummary[];
  digest: string;
}

type SortKey = 'master' | 'updated' | 'created' | 'name';

const SORT_LABELS: Record<SortKey, string> = {
  master: 'Maestro primero',
  updated: 'Actualizado',
  created: 'Creación',
  name: 'Nombre A-Z',
};

function pdfUrl(resume: ResumeRow, download = false): string {
  const params = new URLSearchParams();
  if (resume.updatedAt) params.set('v', resume.updatedAt);
  if (download) params.set('download', 'true');
  return `/api/resumes/${encodeURIComponent(resume.id)}/pdf?${params.toString()}`;
}

/**
 * Renders the real PDF, but only once the card is on screen.
 *
 * The first render of a CV takes a second or two in Reactive Resume, so loading
 * twenty at once would stall the page. The backend caches each render per
 * version, which makes every later view instant.
 */
function PdfPreview({ resume }: { resume: ResumeRow }) {
  const [visible, setVisible] = useState(false);
  const holder = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const node = holder.current;
    if (!node || visible) return;
    if (typeof IntersectionObserver === 'undefined') {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: '300px' },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [visible]);

  return (
    <div
      ref={holder}
      className="relative bg-slate-950 border-b border-slate-800 overflow-hidden"
      style={{ aspectRatio: '1 / 1.294' }}
    >
      {visible ? (
        <iframe
          src={`${pdfUrl(resume)}#toolbar=0&navpanes=0&scrollbar=0&view=FitH`}
          title={`Vista previa de ${resume.name}`}
          loading="lazy"
          className="absolute inset-0 w-full h-full border-0"
        />
      ) : (
        <div className="absolute inset-0 flex items-center justify-center">
          <FileText className="w-8 h-8 text-slate-700" />
        </div>
      )}
    </div>
  );
}

export default function ResumeLibrary({
  showToast,
}: {
  showToast: (text: string, type?: 'info' | 'success' | 'error') => void;
}) {
  const [data, setData] = useState<ResumeListResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, ResumeDetail>>({});
  const [staleRoleMap, setStaleRoleMap] = useState(false);

  // Deleting is irreversible in Reactive Resume, so the button asks first.
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const [view, setView] = useState<'grid' | 'list'>('grid');
  const [sort, setSort] = useState<SortKey>('master');
  const [query, setQuery] = useState('');
  const [tag, setTag] = useState<string>('');

  const fetchResumes = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch('/api/resumes');
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail ?? `Error ${res.status}`);
      setData(body);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchResumes();
  }, [fetchResumes]);

  const allTags = useMemo(() => {
    const set = new Set<string>();
    (data?.resumes ?? []).forEach((resume) => resume.tags.forEach((t) => set.add(t)));
    return [...set].sort();
  }, [data]);

  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const rows = (data?.resumes ?? []).filter((resume) => {
      if (tag && !resume.tags.includes(tag)) return false;
      if (!needle) return true;
      return `${resume.name} ${resume.slug} ${resume.tags.join(' ')}`
        .toLowerCase()
        .includes(needle);
    });

    const byDate = (a: string | null, b: string | null) =>
      new Date(b ?? 0).getTime() - new Date(a ?? 0).getTime();

    return [...rows].sort((a, b) => {
      if (sort === 'name') return a.name.localeCompare(b.name);
      if (sort === 'created') return byDate(a.createdAt, b.createdAt);
      if (sort === 'updated') return byDate(a.updatedAt, b.updatedAt);
      if (a.isMaster !== b.isMaster) return a.isMaster ? -1 : 1;
      return byDate(a.updatedAt, b.updatedAt);
    });
  }, [data, query, tag, sort]);

  const loadDetail = async (id: string) => {
    if (details[id]) return;
    try {
      const res = await fetch(`/api/resumes/${encodeURIComponent(id)}`);
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail ?? `Error ${res.status}`);
      setDetails((current) => ({ ...current, [id]: body }));
    } catch (err) {
      showToast(err instanceof Error ? err.message : String(err), 'error');
    }
  };

  const toggle = async (id: string) => {
    if (expanded === id) {
      setExpanded(null);
      return;
    }
    setExpanded(id);
    await loadDetail(id);
  };

  const setMaster = async (resume: ResumeRow) => {
    setBusy(resume.id);
    try {
      const res = await fetch('/api/resumes/master', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ resumeId: resume.id }),
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail ?? `Error ${res.status}`);
      showToast(body.message ?? 'CV maestro actualizado', 'success');
      setStaleRoleMap(true);
      await fetchResumes();
    } catch (err) {
      showToast(err instanceof Error ? err.message : String(err), 'error');
    } finally {
      setBusy(null);
    }
  };

  const deleteResume = async (resume: ResumeRow) => {
    setBusy(resume.id);
    try {
      const res = await fetch(`/api/resumes/${encodeURIComponent(resume.id)}`, {
        method: 'DELETE',
      });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail ?? `Error ${res.status}`);
      showToast(
        body.detachedApplications
          ? `CV borrado. ${body.detachedApplications} candidatura(s) ya no lo referencian.`
          : 'CV borrado',
        'success',
      );
      setConfirmDelete(null);
      if (expanded === resume.id) setExpanded(null);
      await fetchResumes();
    } catch (error) {
      showToast(error instanceof Error ? error.message : String(error), 'error');
    } finally {
      setBusy(null);
    }
  };

  const rediscover = async () => {
    setBusy('roles');
    try {
      const res = await fetch('/api/roles/discover', { method: 'POST' });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail ?? `Error ${res.status}`);
      showToast(
        `Role map v${body.role_map_version}: ${body.roles} roles, ${body.queries_created} búsquedas nuevas`,
        'success',
      );
      setStaleRoleMap(false);
    } catch (err) {
      showToast(err instanceof Error ? err.message : String(err), 'error');
    } finally {
      setBusy(null);
    }
  };

  const masterBadge = (
    <span className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider px-2.5 py-1 rounded-full bg-indigo-500/15 text-indigo-300 border border-indigo-500/40">
      <Star className="w-3 h-3" />
      Maestro
    </span>
  );

  const actions = (resume: ResumeRow) => (
    <div className="flex items-center gap-1.5">
      <a
        href={pdfUrl(resume)}
        target="_blank"
        rel="noreferrer"
        title="Abrir PDF"
        className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition"
      >
        <ExternalLink className="w-3.5 h-3.5" />
      </a>
      <a
        href={pdfUrl(resume, true)}
        title="Descargar PDF"
        className="p-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition"
      >
        <Download className="w-3.5 h-3.5" />
      </a>
      {!resume.isMaster && (
        <>
          <button
            onClick={() => void setMaster(resume)}
            disabled={busy !== null}
            className="flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-50 transition"
          >
            <Check className="w-3.5 h-3.5" />
            Maestro
          </button>
          {confirmDelete === resume.id ? (
            <span className="flex items-center gap-1">
              <button
                onClick={() => void deleteResume(resume)}
                disabled={busy !== null}
                className="text-xs font-semibold px-2.5 py-1.5 rounded-lg bg-rose-700 hover:bg-rose-600 disabled:opacity-50 transition"
              >
                {busy === resume.id ? 'Borrando…' : 'Confirmar'}
              </button>
              <button
                onClick={() => setConfirmDelete(null)}
                className="text-xs px-2 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 transition"
              >
                No
              </button>
            </span>
          ) : (
            <button
              onClick={() => setConfirmDelete(resume.id)}
              title="Borrar de Reactive Resume"
              className="p-1.5 rounded-lg bg-slate-800 hover:bg-rose-900/60 text-slate-400 hover:text-rose-300 transition"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          )}
        </>
      )}
    </div>
  );

  const detailBlock = (resume: ResumeRow) => {
    const detail = details[resume.id];
    if (!detail) return <p className="text-xs text-slate-500">Cargando…</p>;
    return (
      <>
        {detail.basics?.headline && (
          <p className="text-sm text-slate-300">{detail.basics.headline}</p>
        )}
        <div className="flex flex-wrap gap-2">
          {detail.sections.map((section) => (
            <span
              key={section.key}
              className={`text-[11px] px-2 py-1 rounded-lg border ${
                section.visible
                  ? 'bg-slate-950/60 border-slate-800 text-slate-300'
                  : 'bg-slate-950/30 border-slate-800/60 text-slate-600'
              }`}
            >
              {section.name}
              {section.items > 0 ? ` · ${section.items}` : ''}
            </span>
          ))}
        </div>
        <details className="text-xs text-slate-400">
          <summary className="cursor-pointer text-slate-500 hover:text-slate-300">
            Ver lo que lee el agente
          </summary>
          <pre className="mt-2 p-3 bg-slate-950 border border-slate-800 rounded-xl whitespace-pre-wrap max-h-72 overflow-y-auto text-[11px] leading-relaxed">
            {detail.digest || 'Sin contenido.'}
          </pre>
        </details>
      </>
    );
  };

  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-4 mb-5">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Tus CVs</h2>
          <p className="text-sm text-slate-400 mt-1 max-w-2xl">
            Todos los currículums de Reactive Resume. El CV maestro es la única fuente de verdad:
            de ahí sale el grafo de capacidades, el role map y cada CV adaptado a una oferta.
            Filtra por la etiqueta <code className="text-slate-300">derived</code> para ver solo
            los generados para ofertas concretas.
          </p>
        </div>
        <button
          onClick={() => void fetchResumes()}
          disabled={loading}
          className="flex items-center gap-2 text-sm font-medium px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 disabled:opacity-50 transition"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Actualizar
        </button>
      </div>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2 mb-5">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Buscar por nombre, slug o etiqueta"
            className="w-full bg-slate-900 border border-slate-800 rounded-xl pl-9 pr-3 py-2 text-sm text-slate-200 placeholder:text-slate-600"
          />
        </div>

        <select
          value={sort}
          onChange={(event) => setSort(event.target.value as SortKey)}
          className="bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-sm text-slate-200"
        >
          {(Object.keys(SORT_LABELS) as SortKey[]).map((key) => (
            <option key={key} value={key}>
              {SORT_LABELS[key]}
            </option>
          ))}
        </select>

        {allTags.length > 0 && (
          <select
            value={tag}
            onChange={(event) => setTag(event.target.value)}
            className="bg-slate-900 border border-slate-800 rounded-xl px-3 py-2 text-sm text-slate-200"
          >
            <option value="">Todas las etiquetas</option>
            {allTags.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        )}

        <div className="flex rounded-xl border border-slate-800 overflow-hidden">
          <button
            onClick={() => setView('grid')}
            title="Cuadrícula con vista previa"
            className={`p-2 transition ${
              view === 'grid' ? 'bg-indigo-600 text-white' : 'bg-slate-900 text-slate-400 hover:bg-slate-800'
            }`}
          >
            <LayoutGrid className="w-4 h-4" />
          </button>
          <button
            onClick={() => setView('list')}
            title="Lista"
            className={`p-2 transition ${
              view === 'list' ? 'bg-indigo-600 text-white' : 'bg-slate-900 text-slate-400 hover:bg-slate-800'
            }`}
          >
            <ListIcon className="w-4 h-4" />
          </button>
        </div>
      </div>

      {staleRoleMap && (
        <div className="mb-6 flex flex-wrap items-center gap-3 p-4 rounded-2xl bg-amber-950/30 border border-amber-700/40">
          <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0" />
          <p className="text-sm text-amber-200 flex-1 min-w-[240px]">
            El role map se generó con el CV maestro anterior. Vuelve a lanzar el descubrimiento de
            roles para que se reconstruya con el nuevo.
          </p>
          <button
            onClick={() => void rediscover()}
            disabled={busy !== null}
            className="flex items-center gap-2 text-sm font-medium px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 transition"
          >
            <Sparkles className={`w-4 h-4 ${busy === 'roles' ? 'animate-pulse' : ''}`} />
            Rehacer role map
          </button>
        </div>
      )}

      {error && (
        <div className="mb-6 p-4 rounded-2xl bg-rose-950/30 border border-rose-800/50 text-sm text-rose-200">
          {error}
        </div>
      )}

      {data && !data.masterResumeFound && data.resumes.length > 0 && (
        <div className="mb-6 p-4 rounded-2xl bg-slate-900 border border-slate-800 text-sm text-slate-300">
          El perfil apunta a un CV maestro que ya no existe en Reactive Resume
          {data.masterResumeId ? ` (${data.masterResumeId})` : ''}. Elige uno de la lista.
        </div>
      )}

      {data && (
        <p className="text-xs text-slate-500 mb-3">
          {visible.length} de {data.count} CVs
          {tag ? ` · etiqueta ${tag}` : ''}
        </p>
      )}

      {loading && !data ? (
        <p className="text-sm text-slate-500">Cargando…</p>
      ) : view === 'grid' ? (
        <div className="grid gap-4 grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {visible.map((resume) => (
            <div
              key={resume.id}
              className={`rounded-2xl overflow-hidden border transition flex flex-col ${
                resume.isMaster
                  ? 'border-indigo-500/50 bg-indigo-950/20 shadow-lg shadow-indigo-950/40'
                  : 'border-slate-800 bg-slate-900/60 hover:border-slate-700'
              }`}
            >
              <PdfPreview resume={resume} />

              <div className="p-3 space-y-2 flex-1 flex flex-col">
                <div className="flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="font-semibold text-sm truncate flex items-center gap-1.5">
                      {resume.name}
                      {resume.locked && <Lock className="w-3 h-3 text-slate-500 shrink-0" />}
                    </div>
                    <div className="text-[11px] text-slate-500 truncate">
                      {resume.updatedAt
                        ? new Date(resume.updatedAt).toLocaleDateString()
                        : resume.slug}
                    </div>
                  </div>
                  {resume.isMaster && masterBadge}
                </div>

                {resume.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {resume.tags.slice(0, 3).map((value) => (
                      <span
                        key={value}
                        className="text-[10px] px-2 py-0.5 rounded-md bg-slate-800 text-slate-400"
                      >
                        {value}
                      </span>
                    ))}
                  </div>
                )}

                <div className="mt-auto pt-1 flex items-center justify-between gap-2">
                  {actions(resume)}
                  <button
                    onClick={() => void toggle(resume.id)}
                    className="text-[11px] text-slate-500 hover:text-slate-300 shrink-0"
                  >
                    {expanded === resume.id ? 'Ocultar' : 'Detalles'}
                  </button>
                </div>

                {expanded === resume.id && (
                  <div className="pt-2 border-t border-slate-800 space-y-2">
                    {detailBlock(resume)}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="space-y-2">
          {visible.map((resume) => (
            <div
              key={resume.id}
              className={`border rounded-xl overflow-hidden transition ${
                resume.isMaster
                  ? 'border-indigo-500/50 bg-indigo-950/20'
                  : 'border-slate-800 bg-slate-900/60'
              }`}
            >
              <div className="flex items-center gap-3 px-4 py-3">
                <button
                  onClick={() => void toggle(resume.id)}
                  className="flex items-center gap-3 min-w-0 flex-1 text-left"
                >
                  <FileText
                    className={`w-4 h-4 shrink-0 ${
                      resume.isMaster ? 'text-indigo-400' : 'text-slate-500'
                    }`}
                  />
                  <div className="min-w-0">
                    <div className="font-semibold truncate flex items-center gap-2">
                      {resume.name}
                      {resume.locked && <Lock className="w-3 h-3 text-slate-500" />}
                    </div>
                    <div className="text-xs text-slate-500 truncate">
                      {resume.slug}
                      {resume.updatedAt
                        ? ` · actualizado ${new Date(resume.updatedAt).toLocaleDateString()}`
                        : ''}
                      {resume.tags.length ? ` · ${resume.tags.join(', ')}` : ''}
                    </div>
                  </div>
                </button>

                {resume.isMaster && masterBadge}
                {actions(resume)}
              </div>

              {expanded === resume.id && (
                <div className="px-4 pb-4 border-t border-slate-800 pt-3 grid gap-4 md:grid-cols-[240px_1fr]">
                  <div className="hidden md:block">
                    <PdfPreview resume={resume} />
                  </div>
                  <div className="space-y-3">{detailBlock(resume)}</div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {data && visible.length === 0 && !error && (
        <p className="text-sm text-slate-500">
          {data.count === 0
            ? 'No hay ningún CV en Reactive Resume todavía.'
            : 'Ningún CV coincide con el filtro.'}
        </p>
      )}
    </div>
  );
}
