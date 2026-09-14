import { useState } from 'react';
import { Award, Check, Handshake, Send, Undo2, XOctagon } from 'lucide-react';

export interface OutcomeEntry {
  outcome: string;
  status: string;
  at: string;
  note?: string;
}

interface OutcomeOption {
  key: string;
  label: string;
  icon: JSX.Element;
  className: string;
  /** Statuses the option is offered from. Anything else would be refused anyway. */
  from: string[];
}

const PRE_SUBMISSION = [
  'DISCOVERED',
  'NORMALIZED',
  'EVALUATED',
  'IGNORED',
  'PREPARING',
  'NEEDS_USER_INPUT',
  'READY',
  'READY_FOR_REVIEW',
  'APPLYING',
  'SUBMITTED_UNVERIFIED',
  'BLOCKED',
  'FAILED',
];

const OPTIONS: OutcomeOption[] = [
  {
    key: 'applied',
    label: 'La envié yo',
    icon: <Send className="w-3.5 h-3.5" />,
    className: 'bg-emerald-950 hover:bg-emerald-900 border-emerald-700/60 text-emerald-300',
    from: PRE_SUBMISSION,
  },
  {
    key: 'interview',
    label: 'Entrevista',
    icon: <Handshake className="w-3.5 h-3.5" />,
    className: 'bg-indigo-950 hover:bg-indigo-900 border-indigo-700/60 text-indigo-300',
    from: ['APPLIED', 'SUBMITTED_UNVERIFIED'],
  },
  {
    key: 'offer',
    label: 'Oferta',
    icon: <Award className="w-3.5 h-3.5" />,
    className: 'bg-amber-950 hover:bg-amber-900 border-amber-700/60 text-amber-300',
    from: ['APPLIED', 'INTERVIEW'],
  },
  {
    key: 'rejected',
    label: 'Rechazada',
    icon: <XOctagon className="w-3.5 h-3.5" />,
    className: 'bg-rose-950 hover:bg-rose-900 border-rose-800/60 text-rose-300',
    from: ['APPLIED', 'SUBMITTED_UNVERIFIED', 'INTERVIEW'],
  },
  {
    key: 'withdrawn',
    label: 'Retirada',
    icon: <Undo2 className="w-3.5 h-3.5" />,
    className: 'bg-slate-800 hover:bg-slate-700 border-slate-700 text-slate-300',
    from: ['APPLIED', 'SUBMITTED_UNVERIFIED', 'INTERVIEW', 'READY', 'READY_FOR_REVIEW'],
  },
];

/**
 * Reports what actually happened to an application.
 *
 * Nothing here submits anything. It records what the candidate already did, and
 * it is how interviews reach the RoleDiscoveryAgent, which cannot see them
 * otherwise.
 */
export default function OutcomeControls({
  status,
  runId,
  jobId,
  history = [],
  onRecorded,
  showToast,
  compact = false,
}: {
  status: string;
  runId?: string | null;
  jobId?: string | null;
  history?: OutcomeEntry[];
  onRecorded?: () => void;
  showToast: (text: string, type?: 'info' | 'success' | 'error') => void;
  compact?: boolean;
}) {
  const [busy, setBusy] = useState<string | null>(null);
  const [noteFor, setNoteFor] = useState<string | null>(null);
  const [note, setNote] = useState('');

  const available = OPTIONS.filter((option) => option.from.includes(status));

  const record = async (outcome: string, withNote: string) => {
    const path = runId
      ? `/api/applications/${encodeURIComponent(runId)}/outcome`
      : jobId
        ? `/api/applications/by-job/${encodeURIComponent(jobId)}/outcome`
        : null;
    if (!path) return;

    setBusy(outcome);
    try {
      const res = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ outcome, note: withNote }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail ?? `Error ${res.status}`);
      showToast(`Registrado: ${data.status}`, 'success');
      setNoteFor(null);
      setNote('');
      onRecorded?.();
    } catch (error) {
      showToast(error instanceof Error ? error.message : String(error), 'error');
    } finally {
      setBusy(null);
    }
  };

  if (!available.length && !history.length) return null;

  return (
    <div className="space-y-2">
      {available.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          {!compact && (
            <span className="text-[11px] uppercase tracking-wider text-slate-500 mr-1">
              Registrar
            </span>
          )}
          {available.map((option) => (
            <button
              key={option.key}
              onClick={() => setNoteFor(noteFor === option.key ? null : option.key)}
              disabled={busy !== null}
              className={`flex items-center space-x-1.5 px-3 py-1.5 border rounded-xl text-xs font-semibold transition disabled:opacity-50 ${option.className}`}
            >
              {option.icon}
              <span>{option.label}</span>
            </button>
          ))}
        </div>
      )}

      {noteFor && (
        <div className="flex flex-wrap items-center gap-2 p-2.5 bg-slate-950/60 border border-slate-800 rounded-xl">
          <input
            type="text"
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Nota opcional (fecha, contacto, canal…)"
            className="flex-1 min-w-[180px] bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-200"
          />
          <button
            onClick={() => void record(noteFor, note)}
            disabled={busy !== null}
            className="flex items-center space-x-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 rounded-lg text-xs font-semibold disabled:opacity-50"
          >
            <Check className="w-3.5 h-3.5" />
            <span>{busy ? 'Guardando…' : 'Confirmar'}</span>
          </button>
          <button
            onClick={() => {
              setNoteFor(null);
              setNote('');
            }}
            className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 rounded-lg text-xs"
          >
            Cancelar
          </button>
        </div>
      )}

      {history.length > 0 && (
        <ul className="text-[11px] text-slate-500 space-y-0.5">
          {history.slice(-4).map((entry, index) => (
            <li key={`${entry.outcome}-${index}`}>
              {new Date(entry.at).toLocaleDateString()} · {entry.status}
              {entry.note ? ` · ${entry.note}` : ''}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
