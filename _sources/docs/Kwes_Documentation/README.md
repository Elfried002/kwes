# Kwes — Documentation technique et fonctionnelle

**Version documentaire :** 1.0.0  
**Date :** 15 novembre 2026  
**Produit :** Kwes — Personal Autonomous AI Agent  
**Cible Alpha :** 18 novembre 2026  
**Statut :** Référence de conception — à valider pendant l'implémentation

## Objet de cette archive

Cette documentation décrit le produit Kwes, ses comportements, ses interfaces, ses données, son architecture, ses règles de sécurité et ses critères de validation. Elle est destinée aux développeurs, designers, architectes logiciels, testeurs et agents de programmation.

Elle constitue une source de vérité de conception, pas une preuve que les fonctionnalités décrites sont déjà implémentées.

## Décisions confirmées

- Assistant personnel universel, à identité propre : **Kwes**.
- Autonomie élevée, encadrée par une politique d'autorisation indépendante du LLM.
- DeepSeek comme fournisseur initial de raisonnement.
- ElevenLabs Speech Engine comme voie vocale initiale.
- Interface web/PWA déployée sur Vercel.
- Backend et workers sur un VPS dédié Ubuntu.
- Supabase PostgreSQL et pgvector pour les données et la mémoire.
- VPS initial visé : 4 vCPU, 8 Go RAM, 100 Go NVMe.
- Identité visuelle : sphère hybride constituée de particules.
- Voix initiale : masculine, calme et naturelle.
- Multilinguisme dès la conception, avec validation progressive des langues africaines.
- Alpha à présenter sous forme d'application fonctionnelle et de présentation professionnelle.

## Périmètre réaliste de Kwes

L'Alpha doit démontrer une chaîne réelle : demande → compréhension → plan → contrôle d'autorisation → exécution d'un outil → vérification → compte rendu. Elle inclut l'interface, le chat DeepSeek, une expérience vocale intégrée si la configuration ElevenLabs est disponible, les conversations persistantes, les missions et trois skills de base.

Les appels téléphoniques, paiements, achats engageants, support complet des langues locales et auto-publication de skills sont des évolutions ultérieures, sauf intégration et validation explicites.

## Lecture recommandée

1. `01-product/PRODUCT_VISION.md`
2. `01-product/PRD_ALPHA.md`
3. `02-functional/FEATURE_CATALOG.md`
4. `03-user-experience/USER_JOURNEYS.md`
5. `04-architecture/SYSTEM_ARCHITECTURE.md`
6. `05-ai/AGENT_ORCHESTRATION.md`
7. `06-data/DATA_MODEL.md`
8. `07-api/API_CONTRACTS.md`
9. `08-security/SECURITY_MODEL.md`
10. `12-delivery/IMPLEMENTATION_PLAN.md`

## Index documentaire

| Dossier | Contenu |
|---|---|
| `01-product/` | Vision, PRD, périmètre et exigences |
| `02-functional/` | Catalogue des fonctionnalités, règles métier, cas d'usage |
| `03-user-experience/` | Parcours, écrans, états, accessibilité |
| `04-architecture/` | Architecture, composants, décisions techniques |
| `05-ai/` | Orchestration, LLM, voix, mémoire, langues |
| `06-data/` | Modèle de données, rétention et migrations |
| `07-api/` | Contrats REST, WebSocket et événements |
| `08-security/` | Menaces, autorisations, secrets et audit |
| `09-skills/` | Skills, manifeste, sandbox et cycle de publication |
| `10-infrastructure/` | VPS, Docker, Vercel, sauvegardes et observabilité |
| `11-design/` | Identité visuelle, design system et motion |
| `12-delivery/` | Plan Alpha, tests, critères de sortie et risques |
| `13-demo/` | Scénario de démonstration et script de présentation |
| `decisions/` | Décisions d'architecture (ADR) |

## Conventions

- MUST / DOIT : exigence obligatoire.
- SHOULD / DEVRAIT : recommandation forte.
- MAY / PEUT : option autorisée.
- Les secrets ne doivent jamais être commités.
- Les données externes sont non fiables jusqu'à validation.
- Une action n'est considérée réussie qu'après vérification par un système externe ou une preuve d'exécution.
- Les dates, prix, capacités fournisseurs et langues prises en charge doivent être revalidés auprès des fournisseurs avant mise en production.

## État des décisions

Les choix confirmés sont distingués des propositions à valider. Les détails d'API ElevenLabs, les langues réellement supportées, le fournisseur VPS, les tarifs téléphoniques et la configuration exacte du modèle DeepSeek doivent être vérifiés au moment de l'intégration.
