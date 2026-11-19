# KWES — Équipe agentique (architecture v1.0)

Ce package définit KWES Core et 16 agents spécialisés. Chaque spécialiste possède obligatoirement quatre fichiers : `config.yaml`, `SOUL.md`, `AGENT.md` et `AGENT_SPEC.md`.

## Arborescence
- `core/` : identité, configuration, spécification et procédure de KWES Core.
- `agents/<slug>/` : identité et contrat complet de chaque spécialiste.
- `registry/agents.yaml` : registre central.
- `shared/contracts/` : contrats de sortie partagés.

## Agents inclus
- **KWES BUSINESS** (`business`) — Pilotage des activités
- **KWES SALES** (`sales`) — Vente et développement commercial
- **KWES MARKETING** (`marketing`) — Marketing et visibilité
- **KWES RELATION** (`relation`) — Communication et relation client
- **KWES OPERATIONS** (`operations`) — Opérations, commandes et logistique
- **KWES PERSONAL** (`personal`) — Organisation personnelle
- **KWES LEARNING** (`learning`) — Éducation et apprentissage
- **KWES RESEARCH** (`research`) — Recherche et intelligence informationnelle
- **KWES DOCUMENTS** (`documents`) — Documents et traitement de données
- **KWES VISION** (`vision`) — Perception et création visuelle
- **KWES FINANCE** (`finance`) — Gestion et analyse financière
- **KWES LIFE** (`life`) — Services et assistance quotidienne
- **KWES AUDIT** (`audit`) — Vérification et assurance qualité
- **KWES AUTOMATION** (`automation`) — Automatisation et workflows
- **KWES TECH** (`tech`) — Ingénierie logicielle et assistance technique
- **KWES SECURITY** (`security`) — Sécurité et protection

## Règle d’architecture
Les agents ont une identité propre et des compétences délimitées. KWES Core reste l’unique orchestrateur. Les agents ne s’invoquent pas entre eux directement et ne peuvent modifier les permissions. Les outils listés dans les configurations sont des permissions candidates : ils doivent être reliés au registre d’outils réel et accordés côté serveur.

## Statut
**Architecture et fichiers de définition générés ; aucun déploiement n’est effectué par ce package.** `defined_not_activated` signifie que l’agent est spécifié mais pas nécessairement implémenté, connecté ou testé.

## Ordre de mise en œuvre recommandé
1. Registry, contrats, Policy Engine et Task Orchestrator.
2. Core + agents Business, Sales, Marketing, Relation, Operations, Documents, Research, Vision, Finance, Personal, Learning et Life.
3. Audit, Automation, Tech et Security comme capacités transversales.
4. Connecteurs réels, stockage des livrables, interface Missions, observabilité et tests bout en bout.
5. Activation progressive après tests, sans annoncer de capacité non opérationnelle.

## Modèles
Le périmètre hérité autorise uniquement `gemini-3.8-live` et `gemini-3.8-live-extended-thinking`. Toute modification nécessite validation explicite.


## Configuration v2
Les configurations KWES ont été restructurées à partir des familles de paramètres observées dans le fichier Hermes fourni. Voir `CONFIGURATION_GUIDE.md`, `core/config.yaml`, `agents/*/config.yaml` et `shared/config/`.
