# Système de mémoire — Kwes

## 1. Objectif

La mémoire permet de retrouver le contexte utile entre conversations et missions, sans transformer chaque message en fait permanent.

## 2. Catégories

### Working memory
Contexte temporaire d'une conversation ou mission.

### Episodic memory
Événements : mission créée, décision prise, tâche terminée.

### Semantic memory
Faits utiles et connaissances explicitement conservés.

### Procedural memory
Méthodes et procédures validées, liées aux skills.

## 3. Cycle

1. Extraire les candidats de mémoire.
2. Vérifier leur utilité et leur source.
3. Détecter doublons et contradictions.
4. Appliquer les règles de confidentialité.
5. Demander confirmation si l'information est ambiguë ou sensible.
6. Enregistrer avec provenance et date.
7. Indexer pour recherche si approprié.
8. Appliquer expiration ou suppression.

## 4. Schéma conceptuel

- id ;
- user_id ;
- category ;
- content ;
- source_type ;
- source_id ;
- confidence ;
- created_at ;
- updated_at ;
- expires_at ;
- sensitivity ;
- embedding_ref.

## 5. Recherche

Combiner :
- filtre utilisateur ;
- catégorie ;
- recherche lexicale ;
- similarité vectorielle ;
- récence ;
- confiance.

La recherche vectorielle ne doit jamais traverser les utilisateurs.

## 6. Contrôle utilisateur

L'utilisateur peut :
- voir ce qui est mémorisé ;
- corriger ;
- supprimer ;
- demander une explication de provenance ;
- désactiver une catégorie.

La suppression doit aussi supprimer ou invalider les embeddings et caches dérivés.

## 7. Règles de confidentialité

Ne pas mémoriser par défaut :
- mots de passe ;
- secrets API ;
- numéros de carte ;
- données bancaires complètes ;
- informations sensibles non nécessaires ;
- contenu privé sans finalité explicite.

## 8. Résumés de conversation

Créer un résumé compact lorsque le contexte dépasse le budget. Conserver les messages source selon la politique de rétention et permettre à l'utilisateur de supprimer la conversation.
