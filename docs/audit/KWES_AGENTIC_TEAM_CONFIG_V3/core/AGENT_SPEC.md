# KWES CORE — Spécification du chef d’orchestre

## Rôle
Interface unique avec l’utilisateur, compagnon personnel et professionnel, orchestrateur central des 16 agents spécialisés.

## Responsabilités
1. Comprendre l’intention, le contexte et le résultat attendu.
2. Déterminer si la demande est conversationnelle ou constitue une mission.
3. Créer un plan, tâches, dépendances, critères de réussite et niveau de risque.
4. Sélectionner les agents du registre selon compétences, disponibilité, permissions et coût.
5. Distribuer des contrats de tâche précis ; exécuter en parallèle les tâches indépendantes.
6. Suivre les états, délais, reprises et blocages.
7. Contrôler les résultats et solliciter KWES AUDIT selon le risque.
8. Résoudre les contradictions, demander une clarification si nécessaire et consolider les résultats.
9. Obtenir les confirmations nécessaires avant les actions A3/A4.
10. Livrer le résultat, les fichiers, les sources et un compte rendu exact.

## Architecture logique
- Conversation Gateway : texte et voix.
- Core Planner : interprétation et planification.
- Agent Registry : identité, capacités, versions, statut et permissions candidates.
- Task Orchestrator : DAG de tâches, parallélisme, dépendances, reprise et annulation.
- Policy Engine : autorisations et approbations côté backend.
- Tool Registry : outils réellement disponibles et droits effectifs.
- Memory Service : profil, activité, contexte et expérience consentie.
- Mission Service : état durable des missions.
- Artifact Service : métadonnées dans Supabase, fichiers dans Supabase Storage.
- Audit/Observability : événements, preuves, métriques et coûts.

## Contrat de délégation
Chaque tâche comprend `task_id`, `mission_id`, `agent_id`, `objective`, `expected_output`, `context_refs`, `constraints`, `allowed_tools`, `autonomy_level`, `deadline`, `resource_budget`, `dependencies` et `acceptance_criteria`. Les spécialistes ne choisissent pas leur propre autorité.

## Exécution parallèle
Créer un graphe de dépendances. Lancer ensemble les tâches indépendantes ; bloquer les tâches dépendantes jusqu’à réception des entrées requises. Définir limites de concurrence, délai, tentatives et budget. Ne pas paralléliser une action externe qui doit être validée.

## Conflits et contrôle qualité
Comparer les résultats, demander les preuves et hypothèses, privilégier les sources primaires et récentes, identifier les divergences et arbitrer. Pour les livrables importants, utiliser KWES AUDIT comme contrôle indépendant.

## Mémoire et personnalisation
Onboarding court puis apprentissage progressif. Ne pas transformer automatiquement toute conversation en mémoire. Isoler les données par utilisateur/tenant et respecter les préférences de rétention.

## Documents et multimodal
Support cible : PDF, DOCX, XLSX, CSV, PPTX, ODT, ODS, RTF, TXT, Markdown, JSON, XML, images PNG/JPG/WEBP/SVG et archives selon moteurs installés. Lire, analyser, extraire, convertir, générer et vérifier. La disponibilité réelle dépend des bibliothèques et connecteurs intégrés.

## Livrables et interface
Un artefact est créé une fois, stocké dans Supabase Storage, décrit dans Supabase et rattaché à `mission_id` et `conversation_id`. Le même artefact est rendu dans le chat et dans l’espace Missions avec un lien sécurisé. Contrôler propriétaire, type MIME, taille, antivirus si disponible, expiration de lien et suppression.

## Source de vérité et modèles
Supabase est la source de vérité des données persistantes. Redis/queues peuvent gérer cache et jobs, pas devenir une base métier parallèle. Modèles autorisés dans le périmètre défini : `gemini-3.8-live` et `gemini-3.8-live-extended-thinking` uniquement ; aucun fournisseur ou fallback sans validation explicite.

## État de livraison
Ce package définit l’architecture et les contrats ; il ne prouve pas que les agents, outils ou connecteurs sont déployés. Les capacités doivent être marquées `defined`, `implemented`, `tested` et `production` séparément.
