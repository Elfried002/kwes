# KWES — Architecture des connecteurs d'appareil

Version 1.0 · 16/11/2026 · Statut : **conception validée + socle backend livré**

## 1. Principe

Le moteur d'orchestration ne connaît **aucun** appareil. Il connaît des **capacités**.
Un connecteur déclare ce qu'il sait faire ; l'orchestrateur demande une capacité, jamais un appareil.

```
PWA ─┐
     ├─► API /api/v1 ─► Orchestrateur ─► Policy Engine ─► Device Router ─► Connecteur
Android ─┤                                        │
Desktop ─┘                                        └─► refus explicite si capacité absente
```

Conséquence : ajouter un compagnon Android, un agent Windows/Linux ou un connecteur cloud **ne modifie pas** l'orchestrateur. Il enregistre ses capacités et reçoit des commandes.

## 2. Modèle de données

### `device_connectors`
`id` (uuid) · `user_id` · `connector_id` (ex. `android-companion`) · `platform` (`android`|`ios`|`windows`|`linux`|`macos`|`cloud`) · `connector_version` · `capabilities` (jsonb, liste de capacités déclarées) · `permissions` (jsonb, état accordé/refusé/révoqué) · `status` (`active`|`revoked`|`offline`) · `token_hash` (SHA-256, jamais le jeton en clair) · `last_seen_at` · `created_at` · `updated_at`

### `device_commands`
`id` · `connector_id` · `user_id` · `capability` · `payload` (jsonb, expurgé) · `status` (`queued`|`sent`|`succeeded`|`failed`|`expired`|`refused`) · `result` (jsonb) · `error_code` · `approval_id` (nullable) · `idempotency_key` · `created_at` · `completed_at`

RLS : chaque table est filtrée par `auth.uid() = user_id`, comme le reste du schéma (33 politiques existantes).

## 3. Authentification des connecteurs — indépendante de la PWA

1. L'utilisateur enregistre un connecteur depuis la PWA (session Supabase).
2. Le backend génère un **jeton de connecteur** (32 octets aléatoires), le renvoie **une seule fois**, et stocke uniquement son `sha256`.
3. Le connecteur s'authentifie avec `X-Device-Token`, pas avec la session utilisateur.
4. Révocation = `status='revoked'` + suppression du hash. Toute commande en attente passe `expired`.

Un jeton de connecteur ne donne accès qu'à **ses propres** commandes : impossible de lire les données d'un autre appareil ou d'un autre utilisateur.

## 4. Contrat API

| Méthode | Route | Auth | Rôle |
|---|---|---|---|
| POST | `/api/v1/devices` | session utilisateur | enregistrer un connecteur, retourne le jeton (une fois) |
| GET | `/api/v1/devices` | session utilisateur | lister mes connecteurs, capacités et permissions |
| DELETE | `/api/v1/devices/{id}` | session utilisateur | révoquer |
| POST | `/api/v1/device/heartbeat` | jeton connecteur | signal de vie + état des permissions |
| GET | `/api/v1/device/commands` | jeton connecteur | récupérer les commandes en attente |
| POST | `/api/v1/device/commands/{id}/result` | jeton connecteur | retourner le résultat **réel** |

## 5. Cycle d'une commande

1. L'orchestrateur identifie une capacité nécessaire (`notifications.summarize`).
2. Le **Policy Engine** classe l'action (R0–R4) et décide : `allow`, `require_approval`, `deny`.
3. Le **Device Router** cherche un connecteur actif possédant la capacité **et** la permission accordée.
4. Aucun connecteur → réponse honnête : « cette action n'est pas possible sur cet appareil », avec l'alternative (ex. « ouvrez la notification dans l'application »).
5. Commande créée (`queued`), remise au connecteur au prochain heartbeat.
6. Le connecteur exécute et renvoie le résultat réel ; `status` passe à `succeeded`/`failed`.
7. Le backend **ne conclut jamais au succès** sans ce retour. Timeout → `expired`, jamais `succeeded`.

## 6. Matrice capacité → plateforme

| Capacité | Android | iOS | Desktop | Cloud |
|---|---|---|---|---|
| `sms.read` | rôle SMS par défaut | ❌ impossible | ❌ | ❌ |
| `notifications.read` | permission dédiée | ❌ | ❌ | ❌ |
| `contacts.read` | ✅ | ✅ | ✅ | ❌ |
| `calendar.write` | ✅ | ✅ | ✅ | ✅ |
| `call.dial` | ✅ intent | ✅ intent | ❌ | ❌ |
| `files.pick` | ✅ | ✅ | ✅ | ❌ |
| `screen.capture` | ✅ consentement | ❌ | ✅ consentement | ❌ |
| `shell.exec` | ❌ | ❌ | ✅ après validation R3 | ✅ sur son propre environnement |

## 7. Intégration au Policy Engine

Une commande d'appareil hérite du risque de sa capacité :

| Capacité | Risque | Décision par défaut |
|---|---|---|
| `notifications.read`, `contacts.read`, `files.pick` | R0 | allow |
| `calendar.write`, `call.dial` (préparation) | R1/R2 | allow ou approval selon le contexte |
| `sms.send`, `screen.capture` | R2 | approval |
| `shell.exec`, `files.delete` | R3/R4 | approval explicite ou refus |

Le connecteur **ne peut pas** s'attribuer une capacité : elle est vérifiée côté serveur contre celles enregistrées à l'inscription. Un connecteur compromis ne peut donc pas élargir ses droits.

## 8. Ce qui est livré vs préparé

| Élément | Statut |
|---|---|
| Modèle de données + migration | `implemented` |
| Enregistrement, liste, révocation | `implemented` |
| Authentification par jeton de connecteur | `implemented` |
| Heartbeat + file de commandes + retour de résultat | `implemented` (socle) |
| Device Router dans l'orchestrateur | `planned` (v1.1) |
| Compagnon Android | `planned` (v3) |
| Agent desktop | `planned` (v2) |

## 9. Décisions

- **D-101** — Le jeton de connecteur est distinct de la session utilisateur : un appareil volé ne donne pas accès au compte.
- **D-102** — Aucun résultat n'est accepté sans identifiant de commande et horodatage : pas de « succès » déclaratif.
- **D-103** — La révocation est immédiate et ne dépend pas du connecteur (le serveur refuse, même si l'appareil est hors ligne).
