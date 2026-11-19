import { createClient } from '@supabase/supabase-js';

/**
 * Client Supabase côté navigateur.
 *
 * Seules les variables `VITE_*` sont utilisées : la clé anonyme (anon key) est
 * publique par conception et protégée par les Row Level Security policies.
 * Aucune clé `service_role` ne doit jamais apparaître dans ce fichier.
 */

const rawUrl = (import.meta.env.VITE_SUPABASE_URL ?? '').trim();
const rawAnonKey = (import.meta.env.VITE_SUPABASE_ANON_KEY ?? '').trim();

/** Vrai lorsque les deux variables d'environnement sont renseignées. */
export const supabaseConfigured = rawUrl.length > 0 && rawAnonKey.length > 0;

export const SUPABASE_CONFIG_ERROR =
  'La connexion sécurisée n’est pas configurée sur cette installation (variables VITE_SUPABASE_URL et VITE_SUPABASE_ANON_KEY absentes). Contactez l’administrateur.';

/*
 * Repli inerte : si la configuration manque, on évite de faire planter le rendu.
 * Aucune requête ne pourra aboutir, et l'interface affiche SUPABASE_CONFIG_ERROR.
 */
const FALLBACK_URL = 'http://127.0.0.1:54321';
const FALLBACK_KEY = 'configuration-absente';

export const supabase = createClient(rawUrl || FALLBACK_URL, rawAnonKey || FALLBACK_KEY, {
  auth: {
    // PKCE : le retour de Google arrive en `?code=…` dans la requête. Le flux
    // implicite plaçait les jetons dans le fragment, que le routeur à hash
    // consommait avant Supabase — la connexion aboutissait sur l'écran de
    // connexion, sans session.
    flowType: 'pkce',
    persistSession: true,
    detectSessionInUrl: true,
    autoRefreshToken: true,
    storageKey: 'kwes.auth.supabase',
  },
});
