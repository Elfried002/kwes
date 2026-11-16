# PRD — Kwes

## 1. Objectif

Livrer une application web démontrable qui permet de converser avec Kwes, de créer et suivre des missions, d'utiliser des outils réels limités et de conserver le contexte après fermeture de l'application.

## 2. Périmètre Alpha

### Must have
- PWA responsive.
- Authentification sécurisée.
- Interface de chat.
- Appel réel à DeepSeek via backend.
- Historique des conversations.
- Création de missions et sous-tâches.
- Worker serveur pour les tâches asynchrones.
- Au moins trois skills : `web_research`, `business_planning`, `browser_readonly`.
- Événements de progression.
- Journal d'exécution.
- Gestion des erreurs.
- Voix via intégration ElevenLabs compatible avec le mode Speech Engine retenu, sous réserve de validation de l'API.
- Déploiement frontend Vercel et backend VPS.

### Should have
- Mémoire de préférences simple.
- Résumé de conversation.
- Transcription vocale affichée.
- Notifications dans l'application.
- Export d'un rapport Markdown.
- Indicateur de coût ou d'usage si les données sont disponibles.

### Won't have in Alpha
- Paiement réel.
- Appels téléphoniques sortants.
- Accès à des comptes bancaires.
- Signature ou acceptation contractuelle.
- Auto-publication de skills générés.
- Support certifié de toutes les langues locales.
- Agent desktop avec contrôle complet du système.

## 3. Personas et besoins

### Persona A — Utilisateur délégant
« Je veux demander une mission en langage naturel, voir ce que l'agent prévoit et recevoir un résultat sans surveiller chaque étape. »

### Persona B — Utilisateur vocal
« Je veux parler à Kwes, interrompre sa réponse, voir la transcription et poursuivre dans une autre langue. »

### Persona C — Administrateur de son agent
« Je veux savoir quelles intégrations sont connectées, quelles permissions sont actives et quelles actions ont été réalisées. »

## 4. Exigences fonctionnelles

| ID | Exigence | Priorité |
|---|---|---|
| FR-001 | L'utilisateur peut envoyer un message texte | P0 |
| FR-002 | Kwes répond via DeepSeek côté serveur | P0 |
| FR-003 | Une conversation est persistée | P0 |
| FR-004 | L'utilisateur peut créer une mission | P0 |
| FR-005 | Une mission possède un statut et des sous-tâches | P0 |
| FR-006 | Les tâches longues sont exécutées côté serveur | P0 |
| FR-007 | L'interface reçoit les événements de progression | P0 |
| FR-008 | Chaque exécution d'outil est journalisée | P0 |
| FR-009 | Les actions à risque sont soumises à autorisation | P0 |
| FR-010 | Le mode vocal peut être activé depuis l'interface | P0 si API vocale disponible |
| FR-011 | La voix est configurable | P1 |
| FR-012 | La mémoire de préférences peut être consultée | P1 |
| FR-013 | L'utilisateur peut annuler une mission | P1 |
| FR-014 | L'utilisateur peut exporter un rapport | P1 |
| FR-015 | Les langues sont détectées ou sélectionnées | P1 |
| FR-016 | L'utilisateur peut gérer ses intégrations | P1 |

## 5. Exigences non fonctionnelles

- Sécurité : aucune clé fournisseur dans le navigateur.
- Fiabilité : reprise contrôlée des tâches après redémarrage.
- Observabilité : logs structurés et corrélation par `task_id`.
- Maintenabilité : modules séparés par domaine.
- Accessibilité : navigation clavier, contrastes et labels.
- Performance : interface initiale légère ; latences mesurées.
- Compatibilité : navigateurs modernes desktop et mobile.
- Confidentialité : collecte minimale, rétention documentée.
- Résilience : timeout, retry borné et circuit breaker pour les fournisseurs externes.

## 6. Hypothèses et dépendances

- L'utilisateur achète et configure le VPS.
- Les clés DeepSeek, ElevenLabs et Supabase sont disponibles.
- Le mode précis ElevenLabs choisi autorise l'architecture avec LLM externe.
- Le domaine et les DNS sont disponibles.
- Le fournisseur VPS autorise Docker et les connexions nécessaires.
- Les limites de l'offre ElevenLabs et les langues prises en charge sont vérifiées avant promesse produit.

## 7. Critères de sortie Alpha

1. Déploiement accessible via HTTPS.
2. Un utilisateur authentifié peut discuter avec DeepSeek.
3. Une conversation survit à une déconnexion.
4. Une mission peut être créée et suivie.
5. Un skill exécute une recherche ou une tâche vérifiable.
6. Un résultat est enregistré.
7. Une opération non autorisée est bloquée.
8. Le scénario de démonstration peut être répété.
9. Les erreurs sont visibles et non maquillées en succès.
10. Le système peut être redémarré sans perdre les tâches persistées.
