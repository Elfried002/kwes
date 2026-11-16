# IMPLEMENTATION_STATUS — Kwes

Mis à jour : 16/11/2026 06:00 (Europe/Paris)
Statuts : NOT_STARTED · IN_PROGRESS · IMPLEMENTED · TESTED · BLOCKED · DEFERRED
Aucun statut TESTED sans une exécution réelle enregistrée ci-dessous.

## Fondations
| Élément | Statut | Preuve / remarque |
|---|---|---|
| Documentation extraite (33 docs) | IMPLEMENTED | `_sources/docs/`, copie dans `docs/` |
| Pack de marque extrait (19 fichiers) | IMPLEMENTED | `frontend/public/brand/` |
| Dépôt Git initialisé | IMPLEMENTED | `git init` dans `business/kwes` |
| Contrat d'intégration | IMPLEMENTED | `CONTRACTS.md` |
| Environnement backend (venv) | IMPLEMENTED | fastapi 0.163.1, sqlalchemy 2.1.8, psycopg |

## Lots en cours
| Lot | Responsable | Statut | Périmètre |
|---|---|---|---|
| Backend & API | sous-agent A | IN_PROGRESS | FastAPI, modèles, auth, routes, WS, policy, orchestrateur, worker, 3 skills |
| Frontend & Orb | sous-agent B | IN_PROGRESS | React/TS/Vite, écrans, machine à états Orb, PWA, build |
| Données & Infra | sous-agent C | IN_PROGRESS | migrations SQL + RLS, Docker, CI, docs de déploiement |

## Fonctionnalités Alpha
| ID | Fonctionnalité | Statut |
|---|---|---|
| FR-001 | Envoi de message texte | IN_PROGRESS |
| FR-002 | Réponse DeepSeek côté serveur | IN_PROGRESS (adaptateur + mock si clé absente) |
| FR-003 | Conversation persistée | IN_PROGRESS |
| FR-004 | Création de mission | IN_PROGRESS |
| FR-005 | Statut et sous-tâches | IN_PROGRESS |
| FR-006 | Tâches longues côté serveur (worker) | IN_PROGRESS |
| FR-007 | Événements de progression (WS) | IN_PROGRESS |
| FR-008 | Journal d'exécution | IN_PROGRESS |
| FR-009 | Autorisation des actions sensibles | IN_PROGRESS |
| FR-010 | Mode vocal | IN_PROGRESS (dépend d'ElevenLabs) |
| FR-011 | Voix configurable | NOT_STARTED |
| FR-012 | Mémoire de préférences | NOT_STARTED |
| FR-013 | Annulation de mission | IN_PROGRESS |
| FR-014 | Export de rapport | NOT_STARTED |
| FR-015 | Sélection de langue | IN_PROGRESS (UI) |
| FR-016 | Gestion des intégrations | NOT_STARTED |

## Tests
| Commande | Résultat |
|---|---|
| (à compléter après intégration) | — |

## Blocages connus
1. Aucune clé DeepSeek / ElevenLabs fournie → intégrations livrées avec mock explicitement marqué.
2. Aucun projet Supabase distant accessible → migrations préparées et testées localement si Docker le permet, pas appliquées en production.
3. Aucun VPS/domaine fourni → déploiement préparé, non exécuté.
4. `references/security-playbook.md` annoncé par le README de premium-webcraft mais absent de l'archive.
