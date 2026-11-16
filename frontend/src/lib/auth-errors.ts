/**
 * Traduction des erreurs Supabase Auth en messages produit (français).
 * Fonction pure : testable sans réseau ni navigateur.
 */

interface AuthErrorLike {
  message?: string;
  code?: string;
  status?: number;
  name?: string;
}

function asAuthError(value: unknown): AuthErrorLike | null {
  if (typeof value !== 'object' || value === null) return null;
  return value as AuthErrorLike;
}

const MESSAGES: Record<string, string> = {
  invalid_credentials: 'Adresse e-mail ou mot de passe incorrect.',
  email_not_confirmed:
    'Votre adresse e-mail n’est pas encore confirmée. Ouvrez le lien envoyé par e-mail, puis reconnectez-vous.',
  email_exists: 'Un compte existe déjà avec cette adresse e-mail. Connectez-vous ou réinitialisez votre mot de passe.',
  user_already_exists:
    'Un compte existe déjà avec cette adresse e-mail. Connectez-vous ou réinitialisez votre mot de passe.',
  weak_password:
    'Ce mot de passe est trop faible. Utilisez au moins 8 caractères, avec des lettres et des chiffres.',
  same_password: 'Le nouveau mot de passe doit être différent de l’actuel.',
  signup_disabled: 'La création de compte est désactivée sur ce service. Contactez l’administrateur.',
  email_provider_disabled:
    'La connexion par e-mail est désactivée sur ce service. Utilisez un autre moyen de connexion.',
  provider_disabled:
    'La connexion Google n’est pas encore activée sur ce service. Utilisez l’adresse e-mail et le mot de passe.',
  validation_failed: 'Les informations saisies ne sont pas valides. Vérifiez l’adresse e-mail et réessayez.',
  email_address_invalid: 'Cette adresse e-mail n’est pas acceptée. Utilisez une adresse valide.',
  over_request_rate_limit: 'Trop de tentatives. Patientez une minute avant de réessayer.',
  over_email_send_rate_limit:
    'Trop d’e-mails envoyés en peu de temps. Patientez quelques minutes avant de réessayer.',
  session_not_found: 'Votre session a expiré. Reconnectez-vous.',
  refresh_token_not_found: 'Votre session a expiré. Reconnectez-vous.',
  flow_state_not_found: 'Ce lien a expiré ou a déjà été utilisé. Demandez un nouveau lien.',
  otp_expired: 'Ce lien a expiré. Demandez un nouveau lien de réinitialisation.',
};

function matches(haystack: string, needle: string): boolean {
  return haystack.includes(needle);
}

export function authErrorMessage(error: unknown): string {
  const parsed = asAuthError(error);
  if (!parsed) {
    if (typeof error === 'string' && error.trim()) return error.trim();
    return 'La connexion a échoué. Réessayez dans un instant.';
  }

  const code = parsed.code ?? '';
  if (code && MESSAGES[code]) return MESSAGES[code] ?? '';

  const message = (parsed.message ?? '').trim();
  const lower = message.toLowerCase();

  if (parsed.status === 429) return MESSAGES.over_request_rate_limit ?? '';
  if (parsed.status === 0 || matches(lower, 'failed to fetch') || matches(lower, 'networkerror')) {
    return 'Service de connexion injoignable. Vérifiez votre connexion internet, puis réessayez.';
  }
  if (matches(lower, 'invalid login credentials')) return MESSAGES.invalid_credentials ?? '';
  if (matches(lower, 'email not confirmed')) return MESSAGES.email_not_confirmed ?? '';
  if (matches(lower, 'user already registered') || matches(lower, 'already been registered')) {
    return MESSAGES.user_already_exists ?? '';
  }
  if (matches(lower, 'provider is not enabled') || matches(lower, 'unsupported provider')) {
    return MESSAGES.provider_disabled ?? '';
  }
  if (matches(lower, 'password should be at least') || matches(lower, 'weak password')) {
    return MESSAGES.weak_password ?? '';
  }
  if (matches(lower, 'rate limit') || matches(lower, 'too many requests')) {
    return MESSAGES.over_request_rate_limit ?? '';
  }
  if (matches(lower, 'email rate limit')) return MESSAGES.over_email_send_rate_limit ?? '';
  if (matches(lower, 'token has expired') || matches(lower, 'expired')) return MESSAGES.otp_expired ?? '';

  if (message) return message;
  return 'La connexion a échoué. Réessayez dans un instant.';
}

/** Règles de robustesse appliquées côté client avant l’appel réseau. */
export function validatePassword(password: string, email?: string): string | null {
  if (password.length < 8) return 'Le mot de passe doit contenir au moins 8 caractères.';
  if (password.length > 72) return 'Le mot de passe ne doit pas dépasser 72 caractères.';
  if (email && password.toLowerCase() === email.trim().toLowerCase()) {
    return 'Le mot de passe ne peut pas être identique à l’adresse e-mail.';
  }
  if (!/[a-zA-Z]/.test(password) || !/[0-9]/.test(password)) {
    return 'Ajoutez au moins une lettre et un chiffre pour renforcer le mot de passe.';
  }
  return null;
}

/** Complexité indicative (0 → 4), utilisée pour l'indicateur visuel. */
export function passwordScore(password: string): number {
  let score = 0;
  if (password.length >= 8) score += 1;
  if (password.length >= 12) score += 1;
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score += 1;
  if (/[0-9]/.test(password) && /[^a-zA-Z0-9]/.test(password)) score += 1;
  return Math.min(score, 4);
}
