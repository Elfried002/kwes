# KWES — Matrice de faisabilité, architecture des connecteurs et feuille de route

Version 1.0 · 16/11/2026 · Réponse au document `Kwes_Missions_Fonctionnalites_v1`
Statuts : `implemented` · `tested` · `in_progress` · `planned` · `blocked` · `not_supported`
Règle : une capacité n'est `tested` que si un test ou une exécution réelle est citée. Le catalogue décrit une **vision**, pas l'état livré.

---

## 1. Principe de lecture

| Colonne | Sens |
|---|---|
| PWA | capacité atteignable dans le navigateur installé |
| Backend | capacité exécutée côté serveur (agents, workers, outils) |
| Connecteur natif | nécessite une application compagnon (Android/desktop) |
| Risque | R0 lecture · R1 local réversible · R2 externe · R3 engageant |

**Une PWA ne peut pas** : lire les SMS, lire les notifications d'autres applications, contrôler les appels, lister les applications installées, exécuter des commandes système. Ces lignes sont `not_supported` par la PWA **par conception**, pas par retard de développement.

---

## 2. Matrice — capacités produit (36 domaines)

| # | Domaine | Voie | Statut réel | Preuve / limite |
|---|---|---|---|---|
| 3.1 | Assistant personnel | PWA + Backend | `tested` (socle) | chat DeepSeek réel, contexte de conversation, 116 tests backend |
| 3.2 | Recherche Internet | Backend | `tested` | skill `web_research` (DuckDuckGo + repli Wikipédia), sources citées |
| 3.3 | Navigation web autonome | Backend | `in_progress` | `browser_readonly` = lecture seule avec Playwright ; aucun clic, aucun formulaire |
| 3.4 | Emails | Backend | `planned` | nécessite connecteur IMAP/SMTP + consentement ; infra Zawena non réutilisable telle quelle |
| 3.5 | Appels téléphoniques | Connecteur | `not_supported` (PWA) | impossible en PWA ; nécessite téléphonie (Twilio/Vonage) ou app native |
| 3.6 | Assistant vocal | PWA + Backend | `in_progress` | ElevenLabs opérationnel (voix George, ~1,8 s/phrase) ; STT navigateur + streaming en cours de livraison |
| 3.7 | Agenda / rappels | Backend | `planned` | dépend d'un connecteur calendrier |
| 3.8 | Fichiers et documents | Backend | `planned` | sélecteur système + traitement serveur ; pas de lecture silencieuse du stockage |
| 3.9 | Projets | Backend | `implemented` | missions + étapes + progression réelle en base |
| 3.10 | Entreprise / administration | Backend | `planned` | dépend des documents et de la facturation |
| 3.11 | Prospection commerciale | Backend | `planned` | aucun envoi de masse sans base légale et validation |
| 3.12 | Marketing / contenu | Backend | `planned` | génération de contenu possible, publication non connectée |
| 3.13 | Réseaux sociaux | Backend | `planned` | API officielles uniquement, publication après validation |
| 3.14 | Création de sites | Backend | `planned` | capacités réelles de l'agent, non exposées dans l'UI |
| 3.15 | SEO / AEO / GEO / LLMO | Backend | `planned` | aucune promesse de classement ne sera affichée |
| 3.16 | E-commerce | Backend | `planned` | achat = R3, validation obligatoire |
| 3.17 | Finance personnelle | Backend | `planned` | aucune connexion bancaire en v1 |
| 3.18 | Abonnements | Backend | `planned` | résiliation = R3 |
| 3.19 | Cybersécurité | Backend | `blocked` | pentest/red team suspendus par contrat ; audit autorisé uniquement |
| 3.20 | Automatisation | Backend | `in_progress` | orchestrateur + worker réels ; déclencheurs planifiés à ajouter |
| 3.21 | Programmation | Backend | `planned` | hors périmètre UI actuel |
| 3.22 | Administration système | Backend | `blocked` | accès VPS non fourni ; commandes à risque = R4 sans validation |
| 3.23 | Bases de données | Backend | `implemented` | PostgreSQL + pgvector, RLS active (33 politiques) |
| 3.24 | Agents spécialisés | Backend | `in_progress` | un orchestrateur mono-agent ; multi-agents non exposé |
| 3.25 | Mémoire | Backend | `implemented` | table `memories` + pgvector ; écriture/recherche sémantique non branchées dans l'UI |
| 3.26 | Veille / surveillance | Backend | `planned` | nécessite planificateur + notifications |
| 3.27 | Formation | Backend | `planned` | — |
| 3.28 | Contacts | Backend | `planned` | — |
| 3.29 | Voyages | Backend | `planned` | — |
| 3.30 | Réservations | Backend | `planned` | réservation = R3 |
| 3.31 | Multimédia | Backend | `planned` | — |
| 3.32 | Notifications proactives | Backend + PWA | `implemented` | table + WebSocket ; push hors app non branché |
| 3.33 | Autorisations | Backend | `tested` | policy engine R0–R4 indépendant du LLM, 116 tests |
| 3.34 | Tableau de bord | PWA | `tested` | missions, validations, historique, états réels |
| 3.35 | Langues | Backend | `in_progress` | FR/EN ; langues africaines non validées, non annoncées |
| 3.36 | Autonomie complexe | Backend | `in_progress` | plan → permissions → exécution → vérification ; parallélisme non activé |

---

## 3. Matrice — pilotage du téléphone

| Fonction | PWA | App compagnon Android | iOS | Statut |
|---|---|---|---|---|
| Détecter plateforme / capacités | partiel (UA, API navigateur) | oui | oui | `planned` |
| Lire les SMS | non | rôle SMS par défaut, policies Play | impossible | `not_supported` en PWA |
| Envoyer un SMS | non | oui après consentement | non (sauf `sms:` avec confirmation) | `not_supported` |
| Lire les notifications d'autres apps | non | NotificationListenerService | impossible | `not_supported` |
| Passer un appel | partiel (`tel:`) | oui | oui (`tel:`) | `planned` |
| Contacts | non | oui (permission) | oui (permission) | `planned` |
| Agenda / alarmes | non | oui | oui | `planned` |
| Fichiers / photos | sélecteur système | oui | oui | `planned` |
| Micro / caméra / géoloc | oui avec permission | oui | oui | micro `in_progress` |
| Applications installées | non | partiel | non | `not_supported` |

**Conséquence d'architecture** : la PWA reste l'interface principale. Toute capacité système passe par un **connecteur compagnon** déclaré, avec ses permissions, révocable, et jamais par un contournement.

---

## 4. Matrice — pilotage de l'ordinateur

| Fonction | Statut | Voie |
|---|---|---|
| Lire/créer/déplacer des fichiers | `planned` | agent local avec répertoires autorisés |
| Naviguer et remplir des formulaires | `in_progress` | Playwright côté serveur (lecture aujourd'hui, actions après validation) |
| Commandes système | `blocked` | nécessite un agent local et une validation R3/R4 |
| Capture d'écran / automatisation visuelle | `planned` | agent local, permission explicite, arrêt sur écran inconnu |

---

## 5. Contrat minimal d'un connecteur (à respecter pour Android et desktop)

```json
{
  "connector_id": "android-companion",
  "platform": "android",
  "supported_versions": ">=13",
  "connector_version": "0.1.0",
  "capabilities": ["notifications.read", "contacts.read", "calendar.write"],
  "permissions_required": ["BIND_NOTIFICATION_LISTENER_SERVICE", "READ_CONTACTS"],
  "connection_state": "connected|disconnected|revoked",
  "commands": [{"name": "notifications.summarize", "schema": "..."}],
  "results": [{"name": "notifications.summarized", "schema": "..."}],
  "limits": ["no SMS on iOS", "no silent background send"],
  "approval_policy": "R2 -> confirmation explicite",
  "audit_log": true,
  "revocation": "POST /connectors/{id}/revoke"
}
```

Vérification avant toute commande : connecteur connecté → plateforme compatible → permission accordée → utilisateur authentifié → action autorisée par la politique → confirmation obtenue → paramètres valides. Sinon : expliquer la limite et proposer une alternative.

---

## 6. Feuille de route

### v1 — socle (en cours de livraison)
PWA installable · auth Supabase · chat texte · **conversation vocale** · missions et étapes · 3 skills · validations · journal · notifications in-app · RLS.

### v1.1 — confort et mémoire
Mémoire consultable et éditable dans l'UI · recherche sémantique pgvector · tâches planifiées · notifications push · mode hors ligne dégradé.

### v2 — connecteurs personnels
Email (IMAP/SMTP) · agenda · fichiers · veille planifiée · connecteur desktop en lecture seule.

### v3 — compagnon Android
Notifications (service dédié) · contacts · agenda · appels via intents · aucune lecture SMS hors rôle système explicite.

### Hors périmètre assumé
SMS iOS · contrôle d'applications tierces · élévation de privilèges · contournement de CAPTCHA.

---

## 7. Critères d'acceptation du prochain lot

1. Voix : parler → réponse audio en moins de 3 s après la fin de la phrase ; interruption fonctionnelle ; Orb cohérente avec l'état réel.
2. Mémoire : une préférence énoncée est retrouvée dans une nouvelle conversation.
3. Planification : une mission planifiée s'exécute sans onglet ouvert.
4. Chaque capacité livrée : test automatisé **et** vérification manuelle consignée.
