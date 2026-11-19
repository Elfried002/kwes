import { useCallback, useEffect, useState } from 'react';
import { apiRequest, errorMessage, isApiError } from '../lib/api';

interface Overview {
  role: string;
  environment: string;
  tenants: number;
  members: number;
  missions: { total: number; last_30d: number; running: number; failed: number };
  agent_runs: number;
  alerts_open: number;
  llm: { calls: number; input_tokens: number; output_tokens: number; cost: number | null };
  generated_at: string;
}

interface TenantRow {
  id: string;
  name: string;
  kind: string;
  members: number;
  missions: number;
  created_at: string | null;
}

interface MissionRow {
  id: string;
  tenant_id: string | null;
  title: string;
  status: string;
  error_code: string | null;
  created_at: string | null;
}

interface UsageRow {
  model: string;
  provider: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  avg_duration_ms: number;
  cost: number | null;
}

const nombre = (valeur: number): string => new Intl.NumberFormat('fr-FR').format(valeur);

export function AdminScreen() {
  const [vue, setVue] = useState<Overview | null>(null);
  const [tenants, setTenants] = useState<TenantRow[]>([]);
  const [missions, setMissions] = useState<MissionRow[]>([]);
  const [usage, setUsage] = useState<UsageRow[]>([]);
  const [erreur, setErreur] = useState<string | null>(null);
  const [refuse, setRefuse] = useState(false);

  const charger = useCallback(async () => {
    try {
      const [o, t, m, u] = await Promise.all([
        apiRequest<Overview>('/admin/overview'),
        apiRequest<{ items: TenantRow[] }>('/admin/tenants?limit=20'),
        apiRequest<{ items: MissionRow[] }>('/admin/missions?limit=20'),
        apiRequest<{ models: UsageRow[] }>('/admin/usage?days=30'),
      ]);
      setVue(o);
      setTenants(t.items);
      setMissions(m.items);
      setUsage(u.models);
      setErreur(null);
    } catch (cause) {
      if (isApiError(cause) && cause.status === 403) {
        setRefuse(true);
        return;
      }
      setErreur(errorMessage(cause));
    }
  }, []);

  useEffect(() => {
    void charger();
  }, [charger]);

  if (refuse) {
    return (
      <div className="page">
        <h1 style={{ fontSize: '1.25rem' }}>Cockpit</h1>
        <p className="muted">Cet espace est réservé à l’administration de KWES.</p>
      </div>
    );
  }

  if (erreur) {
    return (
      <div className="page">
        <p className="notice notice--danger" role="alert">{erreur}</p>
      </div>
    );
  }

  if (!vue) return <div className="page"><p className="muted">Chargement du cockpit…</p></div>;

  return (
    <div className="page stack">
      <header>
        <h1 style={{ fontSize: '1.35rem' }}>Cockpit</h1>
        <p className="muted" style={{ fontSize: '0.75rem' }}>
          Environnement : <strong>{vue.environment}</strong> · rôle {vue.role} · données du{' '}
          {new Date(vue.generated_at).toLocaleString('fr-FR')}
        </p>
      </header>

      <section className="grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 8 }}>
        <div className="card"><div className="muted" style={{ fontSize: '0.75rem' }}>Espaces</div><strong>{nombre(vue.tenants)}</strong></div>
        <div className="card"><div className="muted" style={{ fontSize: '0.75rem' }}>Membres</div><strong>{nombre(vue.members)}</strong></div>
        <div className="card"><div className="muted" style={{ fontSize: '0.75rem' }}>Missions (30 j)</div><strong>{nombre(vue.missions.last_30d)}</strong></div>
        <div className="card"><div className="muted" style={{ fontSize: '0.75rem' }}>En cours</div><strong>{nombre(vue.missions.running)}</strong></div>
        <div className="card"><div className="muted" style={{ fontSize: '0.75rem' }}>Échecs</div><strong>{nombre(vue.missions.failed)}</strong></div>
        <div className="card"><div className="muted" style={{ fontSize: '0.75rem' }}>Alertes ouvertes</div><strong>{nombre(vue.alerts_open)}</strong></div>
      </section>

      <section className="card stack" style={{ gap: 6 }}>
        <strong>Consommation LLM (30 jours)</strong>
        <p className="muted" style={{ fontSize: '0.8125rem', margin: 0 }}>
          {nombre(vue.llm.calls)} appels · {nombre(vue.llm.input_tokens)} jetons entrée ·{' '}
          {nombre(vue.llm.output_tokens)} jetons sortie
        </p>
        <p className="muted" style={{ fontSize: '0.75rem', margin: 0 }}>
          Coût monétaire : <strong>inconnu</strong> — aucun barème validé n’est appliqué.
        </p>
      </section>

      <section className="card stack" style={{ gap: 6 }}>
        <strong>Modèles utilisés</strong>
        {usage.length === 0 ? <p className="muted" style={{ fontSize: '0.8125rem' }}>Aucun appel enregistré.</p> : null}
        {usage.map((ligne) => (
          <p key={ligne.model} className="muted" style={{ fontSize: '0.75rem', margin: 0 }}>
            {ligne.model} · {ligne.provider} · {nombre(ligne.calls)} appels ·{' '}
            {nombre(ligne.input_tokens)}/{nombre(ligne.output_tokens)} jetons ·{' '}
            {Math.round(ligne.avg_duration_ms)} ms moyen
          </p>
        ))}
      </section>

      <section className="card stack" style={{ gap: 6 }}>
        <strong>Dernières missions</strong>
        {missions.map((mission) => (
          <p key={mission.id} className="muted" style={{ fontSize: '0.75rem', margin: 0 }}>
            {mission.title} — <strong>{mission.status}</strong>
            {mission.error_code ? ` (${mission.error_code})` : ''}
          </p>
        ))}
      </section>

      <section className="card stack" style={{ gap: 6 }}>
        <strong>Espaces</strong>
        {tenants.map((tenant) => (
          <p key={tenant.id} className="muted" style={{ fontSize: '0.75rem', margin: 0 }}>
            {tenant.name} · {tenant.members} membre(s) · {tenant.missions} mission(s)
          </p>
        ))}
      </section>
    </div>
  );
}
