# Kwes — Données personnelles, conformité et analyse de risques

**Statut du document** : fondations techniques et documentaires. **Kwes n'est ni certifié ni
officiellement conforme** à ce jour : aucune certification ISO/IEC 27001 ou 27701 n'a été obtenue,
aucun audit externe n'a été réalisé, et les obligations déclaratives auprès de l'ARTCI n'ont pas été
accomplies. Ce document prépare le travail, il ne le remplace pas.

Référentiels utilisés comme grille de lecture : loi ivoirienne n° 2013-450 relative à la protection
des données à caractère personnel, exigences ARTCI, ISO/IEC 27001:2022 (annexe A), ISO/IEC 27701
(protection de la vie privée), NIST CSF 2.0, OWASP ASVS, OWASP Top 10 for LLM Applications,
NIST AI RMF. Toute qualification juridique doit être validée par un juriste.

---

## 1. Inventaire des données

| Donnée | Table / emplacement | Finalité | Base | Sensibilité |
|---|---|---|---|---|
| Identifiant de compte, e-mail | `profiles`, `auth.users` | authentification, affichage | contrat | personnelle |
| Nom d'affichage, langue, fuseau | `profiles` | personnalisation | contrat | personnelle |
| Conversations et messages | `conversations`, `messages` | fournir le service | contrat | personnelle (contenu libre) |
| Missions, étapes, exécutions | `tasks`, `task_steps`, `executions` | exécution et traçabilité | contrat | personnelle |
| Mémoires durables | `memories` | personnalisation, consentement explicite | consentement | peut être sensible |
| Documents produits | `documents` | livrable de la mission | contrat | personnelle |
| Preuves de recherche | `evidence` | citation et vérifiabilité | intérêt légitime | contenu public recopié |
| Journal d'audit | `audit_logs` | sécurité, preuve | intérêt légitime | techniques |
| Approbations | `approvals` | preuve de consentement | obligation légale | personnelle |
| Sessions vocales (durées, coût estimé) | `voice_sessions` | maîtrise des coûts | intérêt légitime | technique |
| Audio des conversations | **non conservé** (transite seulement) | — | — | — |

Aucune donnée n'est vendue, louée ou utilisée pour entraîner un modèle par Kwes.

---

## 2. Registre des traitements (extrait)

| Traitement | Finalité | Catégories | Destinataires | Durée | Mesures |
|---|---|---|---|---|---|
| T1 — Conversation texte et voix | fournir l'assistant | contenu, identifiant | DeepSeek (raisonnement), Google (voix) | durée du compte | TLS, RLS, audit, pas de clé côté navigateur |
| T2 — Missions et outils | exécuter des tâches | contenu, résultats | Google (voix), SearXNG (auto-hébergé) | durée du compte | Policy Engine, approbations, verrou, audit |
| T3 — Recherche web et preuves | documenter les réponses | requêtes, pages publiques | SearXNG local, DuckDuckGo, Wikipédia | 24 h (cache), compte (preuves) | SSRF, allowlist, neutralisation d'injection |
| T4 — Mémoire | personnaliser | faits déclarés | aucun tiers | jusqu'à suppression | consentement explicite, isolation, expiration |
| T5 — Documents | produire des livrables | contenu | aucun tiers | jusqu'à suppression | accès propriétaire uniquement |
| T6 — Journalisation | sécurité et preuve | identifiants, actions | aucun tiers | 12 mois (cible) | expurgation des secrets |

---

## 3. Fournisseurs et sous-traitants

| Fournisseur | Rôle | Données exposées | Localisation | Statut contractuel |
|---|---|---|---|---|
| Supabase | authentification, PostgreSQL | compte, contenu | à confirmer (région du projet) | à formaliser |
| Vercel | hébergement du frontend | contenu du navigateur | à confirmer | à formaliser |
| DeepSeek | raisonnement des réponses | contenu des messages | à confirmer | **transfert hors CI à analyser** |
| Google (Gemini) | voix, embeddings à venir | audio, texte | à confirmer | **transfert hors CI à analyser** |
| DuckDuckGo, Wikipédia | recherche d'appoint | requêtes (sans identité) | UE/États-Unis | conditions publiques |
| SearXNG | métamoteur auto-hébergé | requêtes | serveur Kwes | aucune transmission à un tiers unique |
| Hébergeur du VPS | infrastructure | ensemble des données | à confirmer | à formaliser |

Aucun de ces statuts ne peut être présenté comme conforme avant signature des accords de
sous-traitance et analyse des transferts internationaux.

---

## 4. Conservation et suppression

| Donnée | Conservation cible | Mécanisme |
|---|---|---|
| Conversations / messages | jusqu'à suppression par l'utilisateur | suppression en cascade |
| Missions et étapes | 12 mois | purge planifiée (à implémenter) |
| Preuves de recherche | 12 mois | purge planifiée (à implémenter) |
| Mémoires | jusqu'à suppression ou expiration | `expires_at` (filtre à appliquer en lecture) |
| Documents | jusqu'à suppression | suppression par l'utilisateur |
| Journal d'audit | 12 mois | rotation (à implémenter) |
| Sessions vocales | 90 jours | purge planifiée (à implémenter) |

**Droit à l'effacement** : la suppression du compte supprime en cascade profil, conversations,
missions, mémoires, documents, preuves (clés étrangères `on delete cascade`). Les journaux d'audit
sont conservés puis purgés, sauf obligation de preuve contraire.

**Droits** : accès (export à ajouter), rectification (édition du profil), effacement, opposition
(arrêt de la mémoire), portabilité (export JSON à ajouter). **Non implémenté aujourd'hui** : export
complet et purge automatique.

---

## 5. Procédure d'incident

1. **Détection** : alerte technique, signalement utilisateur, revue de journal.
2. **Qualification** (24 h) : nature, données touchées, personnes concernées, gravité.
3. **Contention** : révocation des jetons et clés concernés, suspension du service si nécessaire.
4. **Notification** : autorité (ARTCI) et personnes concernées selon les délais légaux applicables,
   après validation juridique.
5. **Correction** : correctif, test de non-régression, retour d'expérience écrit.
6. **Traçabilité** : dossier d'incident conservé, sans secret.

Contact : à désigner formellement (responsable de traitement et point de contact ARTCI).

---

## 6. Analyse de risques (extrait)

| Risque | Vraisemblance | Impact | Mesures existantes | Reste à faire |
|---|---|---|---|---|
| Fuite de données entre utilisateurs | faible | élevé | RLS 42 politiques, filtres `user_id`, tests | audit RLS périodique |
| Injection de prompt via page web | élevée | moyen | neutralisation phrase par phrase, contenu traité comme donnée, pas d'outil R2 | tests adversariaux continus |
| Exfiltration de secrets par le modèle | faible | élevé | secrets hors contexte, outils sans accès aux clés, sandbox sans réseau | rotation des clés |
| Exécution de code malveillant | moyenne | élevé | conteneur jetable, réseau none, cap-drop, uid 65534, limites CPU/RAM, proxy Docker restreint | rootless (Podman/gVisor) |
| Déni de service par boucle agentique | moyenne | moyen | 2 tours d'outils, 3 appels/tour, quotas, timeouts | budget par utilisateur |
| Compromission du VPS | faible | critique | systemd durci, services non root, TLS | journalisation centralisée, IDS |
| Accès non autorisé via JWT | faible | élevé | ES256 + JWKS + iss/aud/exp, HS256 refusé en prod | rotation des clés Supabase |
| Perte de données | faible | élevé | sauvegardes, migrations réversibles | test de restauration |
| Sous-traitant non conforme | moyenne | élevé | minimisation | accords de sous-traitance |

Mapping OWASP Top 10 for LLM : LLM01 injection (neutralisation + policy), LLM02 fuite d'information
(RLS + expurgation), LLM06 agentivité excessive (Policy Engine, R0–R4, approbations), LLM07 fuite de
prompt système (instructions non exposées), LLM08 embeddings (à traiter en P2), LLM10 consommation
non maîtrisée (quotas, budgets, timeouts).

---

## 7. Ce qui n'est pas fait

- Aucune déclaration ARTCI, aucun registre déposé.
- Aucun accord de sous-traitance signé.
- Aucune analyse juridique des transferts (DeepSeek, Google).
- Aucune purge automatique, aucun export de données utilisateur.
- Aucun DPO désigné.
- Aucune certification, aucun audit externe, aucune attestation.

Ces points relèvent d'une décision d'Elfried et d'un accompagnement juridique : ils ne peuvent pas
être traités par l'ingénierie seule, et ne doivent pas être annoncés comme faits.
