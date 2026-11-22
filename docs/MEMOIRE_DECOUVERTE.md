# Découverte du premier contact et apprentissage progressif

État : **en production** (backend `api.agent-kwes.com`, 22/11/2026).

## Ce que fait Kwes

1. **Première conversation** — si l'utilisateur n'a aucun fait mémorisé et que la
   conversation compte au plus 4 messages, Kwes se présente en une phrase puis
   pose **une seule** question, trois au maximum : comment l'appeler, ce qu'il
   fait, ce qu'il attend en priorité. Il rebondit sur chaque réponse et termine
   par un résumé de ce qu'il a retenu. Aucune liste, aucun formulaire.
2. **Apprentissage** — à chaque tour, les faits durables énoncés (prénom,
   activité, projets, préférences, contraintes, objectifs, langue de travail)
   sont extraits et enregistrés sans que l'utilisateur ait à le demander.
3. **Rappel** — les faits sont réinjectés dans le prompt et réutilisés
   naturellement ; Kwes ne redemande pas une information connue et ne prétend
   jamais se souvenir d'autre chose que de ce qui est en base.

## Où c'est implémenté

| Élément | Fichier |
|---|---|
| Détection, plan de découverte, consignes | `backend/app/agent/discovery.py` |
| Extraction, déduplication, filtre de secrets | `backend/app/agent/memory_facts.py` |
| Câblage conversation (direct + SSE) | `backend/app/agent/orchestrator.py` |
| Prompt de la boucle d'outils | `backend/app/agent/tools.py` |
| État persisté | `supabase/migrations/0021_user_onboarding.sql` |
| Flux texte (SSE) | `backend/app/agent/live_reasoner.py` |

## Règles tenues

- **Une question à la fois** : la consigne est injectée par tour
  (`PHASE DE DÉCOUVERTE`, étape n/3) ; le modèle ne reçoit jamais une liste.
- **Jamais rejouée** : la séquence est close en base (`user_onboarding.completed_at`)
  dès le résumé final ; une conversation ultérieure ne la rejoue pas, même si
  l'utilisateur n'a rien dit de lui.
- **Arrêt dès que des faits existent** : un utilisateur qui a déjà des faits
  n'entre jamais en découverte, et un prénom donné d'emblée fait sauter la
  question correspondante.
- **Non bloquant** : extraction par règles, aucun appel modèle ; une lecture et
  une écriture SQL par tour (quelques millisecondes). Un échec d'écriture est
  journalisé et ne casse jamais la réponse.
- **Dédupliqué** : un même sujet (« Prénom ») met à jour la ligne existante ;
  un fait déjà présent à l'identique n'est pas réécrit. Une demande explicite
  (« retiens que… ») est laissée à l'outil `remember`, pour éviter un doublon.
- **Sans données sensibles** : mot de passe, numéro de carte, jeton, clé d'API,
  IBAN — un message qui en contient un n'est jamais mémorisé.
- **Scoping** : `user_id` = auteur du message, `tenant_id` estampillé par le
  contexte de requête, RLS forcée (`user_onboarding` : politique
  `user_id = auth.uid()`). L'injection ne lit que les faits de l'utilisateur
  courant, dans son espace de travail.

## Preuves

```bash
cd backend && .venv/bin/python -m pytest tests/ -q      # 349 passed, 4 skipped
cd frontend && npx tsc --noEmit && npx vitest run       # 148 passed
backend/.venv/bin/python backend/tools/recette_onboarding_stream.py  # recette SSE
```

Recette de production (compte `verif3081@zawena.com`, faits de test uniquement) :
séquence complète en 4 tours puis rappel dans une conversation neuve, trois
faits écrits en base, séquence close, aucune reprise dans la conversation
suivante.

## Limites assumées

- L'extraction est déterministe : une formulation très indirecte peut ne pas
  être captée. Le modèle garde `remember` pour les cas explicites.
- La liste `/memory` de l'API reste scopée à l'espace de travail ; seule
  l'injection dans le prompt est strictement personnelle.
- Les faits extraits ne sont pas vectorisés (pas d'embedding) : le rappel
  repose sur les 12 derniers faits (`max_memories_in_prompt`).
