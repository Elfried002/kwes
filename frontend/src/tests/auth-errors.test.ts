import { describe, expect, it } from 'vitest';
import { authErrorMessage, passwordScore, validatePassword } from '../lib/auth-errors';

describe('mapping des erreurs d’authentification', () => {
  it('identifiants invalides → message produit', () => {
    expect(authErrorMessage({ code: 'invalid_credentials', message: 'Invalid login credentials' })).toBe(
      'Adresse e-mail ou mot de passe incorrect.',
    );
  });

  it('e-mail non confirmé → invite à ouvrir le lien reçu', () => {
    expect(authErrorMessage({ code: 'email_not_confirmed' })).toContain('pas encore confirmée');
  });

  it('trop de tentatives (429) → invite à patienter', () => {
    expect(authErrorMessage({ status: 429, message: 'Request rate limit reached' })).toContain(
      'Trop de tentatives',
    );
  });

  it('fournisseur Google désactivé → message explicite', () => {
    expect(authErrorMessage({ message: 'Unsupported provider: provider is not enabled' })).toContain(
      'Google',
    );
  });

  it('réseau indisponible → message de connectivité', () => {
    expect(authErrorMessage({ message: 'Failed to fetch' })).toContain('injoignable');
  });

  it('code inconnu mais message serveur → message conservé', () => {
    expect(authErrorMessage({ code: 'unexpected_failure', message: 'Database error saving new user' })).toBe(
      'Database error saving new user',
    );
  });

  it('valeur non exploitable → message générique', () => {
    expect(authErrorMessage(null)).toBe('La connexion a échoué. Réessayez dans un instant.');
  });
});

describe('robustesse du mot de passe', () => {
  it('refuse moins de 8 caractères', () => {
    expect(validatePassword('Ab1')).toContain('au moins 8 caractères');
  });

  it('refuse un mot de passe sans chiffre', () => {
    expect(validatePassword('motdepasse')).toContain('une lettre et un chiffre');
  });

  it('refuse un mot de passe identique à l’e-mail', () => {
    expect(validatePassword('secret1234', 'secret1234')).toContain('identique');
  });

  it('accepte un mot de passe conforme', () => {
    expect(validatePassword('Kwes2026!', 'vous@exemple.com')).toBeNull();
  });

  it('note la robustesse de 0 à 4', () => {
    expect(passwordScore('abc')).toBe(0);
    expect(passwordScore('Kwes2026!Secret')).toBe(4);
  });
});
