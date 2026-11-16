# Modèle de sécurité — Kwes

## 1. Objectif

Empêcher une instruction malveillante, une erreur du modèle ou une compromission d'intégration de provoquer une action non autorisée.

## 2. Frontières de confiance

- Navigateur : non fiable.
- LLM : non fiable comme décideur de permissions.
- Pages web et emails : contenu non fiable.
- Skills : code exécutable soumis à isolation.
- Backend : point d'application des politiques.
- Fournisseurs externes : dépendances à surveiller.

## 3. Menaces principales

| Menace | Mesure |
|---|---|
| Vol de clé API | secrets côté serveur, rotation |
| Prompt injection | séparation instructions/données, contrôle outil |
| Action non autorisée | policy engine |
| SSRF | allowlist réseau, blocage IP privées et métadonnées cloud |
| XSS | échappement, CSP |
| CSRF | protections adaptées aux cookies |
| WebSocket abusif | auth, origin check, rate limit |
| Fuite entre utilisateurs | RLS et contrôles backend |
| Skill malveillant | sandbox, permissions minimales |
| Replay d'approbation | expiration et payload hash |
| Doublon d'achat futur | idempotence et vérification externe |
| Exfiltration | allowlist egress et redaction |

## 4. Policy Engine

Décision basée sur :
- identité utilisateur ;
- outil ;
- action ;
- ressource ;
- niveau de risque ;
- permission active ;
- budget ;
- domaine autorisé ;
- approbation valide.

Le modèle ne peut ni modifier ni contourner ce moteur.

## 5. Niveaux de risque

- R0 : lecture.
- R1 : préparation locale/réversible.
- R2 : communication ou modification externe.
- R3 : engagement financier/légal.
- R4 : action interdite.

La matrice détaillée est dans `02-functional/BUSINESS_RULES.md`.

## 6. Secrets

- variables serveur ou gestionnaire de secrets ;
- aucun `.env` commité ;
- fichiers `.env.example` sans valeurs ;
- permissions minimales ;
- rotation et révocation documentées ;
- chiffrement des secrets persistés ;
- logs expurgés.

## 7. Isolation des skills

- processus ou conteneur isolé ;
- filesystem temporaire ;
- limites CPU/RAM ;
- timeout ;
- réseau désactivé par défaut ;
- allowlist de domaines si nécessaire ;
- aucune socket Docker accessible au skill ;
- aucun montage du système hôte ;
- sortie validée par schéma.

## 8. Browser security

- domaines autorisés ;
- blocage des IP privées, localhost et metadata endpoints ;
- gestion des téléchargements ;
- profil navigateur isolé ;
- cookies chiffrés et scopes limités ;
- pas de contournement CAPTCHA ou contrôle d'accès ;
- confirmation avant action externe sensible.

## 9. Audit

Chaque décision d'autorisation et chaque action importante doit être journalisée. Les données sensibles sont expurgées. Les journaux ne doivent pas contenir de tokens, mots de passe ou données de paiement complètes.

## 10. Réponse incident

1. suspendre les clés compromises ;
2. désactiver l'intégration ou le skill concerné ;
3. préserver les logs utiles ;
4. évaluer les actions effectuées ;
5. notifier l'utilisateur si nécessaire ;
6. restaurer depuis un état connu ;
7. documenter la cause et les corrections.

## 11. Référentiels

S'inspirer d'OWASP ASVS, OWASP Top 10, OWASP Top 10 for LLM Applications et des bonnes pratiques de sécurité cloud. Vérifier les versions actuelles avant audit formel.
