# Guide des configurations KWES

## Fichiers
- `core/config.yaml` : configuration de KWES Core, orchestrateur central.
- `agents/<slug>/config.yaml` : configuration propre à chaque agent spécialiste.
- `shared/config/defaults.yaml` : valeurs communes de référence.
- `shared/config/policy.yaml` : règles d'autorisation et niveaux A0–A4.
- `registry/agents.yaml` : registre des 16 agents et chemins de leurs fichiers.

## Référence Hermes
Le fichier Hermes transmis a servi de référence structurelle pour les familles modèle, agent, runtime, terminal, navigateur, garde-fous de boucle d'outils, mémoire, délégation, voix, toolsets, sécurité et approbations. Les noms et la sémantique ont été adaptés à KWES : ce n'est pas un fichier Hermes directement compatible.

## Modèles
Seuls `gemini-3.8-live` et `gemini-3.8-live-extended-thinking` sont autorisés dans cette version. Aucun basculement automatique vers un autre fournisseur ou modèle n'est permis.

## Sécurité
- Refus par défaut : aucun outil n'est utilisable sans autorisation explicite.
- KWES Core est le seul composant autorisé à dispatcher les agents.
- Le moteur de politiques doit être appliqué côté serveur, indépendamment du modèle.
- A3 et A4 sont soumis à confirmation selon la politique.
- KWES Pay reste désactivé.
- Les intégrations non testées restent désactivées.

## Statut
`architecture_defined_not_deployed` signifie que la configuration est définie mais que son chargement, son application et ses intégrations doivent encore être implémentés et testés. Les capacités déclarées ne prouvent pas que les outils sont déjà disponibles.
