# Kwes — exécution du brief du 18 novembre 2026

**Commit** : `4807587` · **Branche** : `alpha/jour-1` · **Règle appliquée** : exécution
autonome, arrêt uniquement sur blocage externe réel.

---

## 1. Ce qui est fait et vérifié

### 1.1 Contrainte des deux modèles — appliquée

Le brief (§4.3) n'autorise que `gemini-3.8-live` et
`gemini-3.8-live-extended-thinking`. Appliqué, et voici ce que la vérification
directe de l'API a montré :

| Vérification | Résultat mesuré |
|---|---|
| `generateContent` sur `gemini-3.8-live` | **404** — modèle non supporté pour cette API |
| Sortie `TEXT` seule en session Live | **refusée** (`The requested combination of response modalities (TEXT) is not supported`) |
| Sortie `AUDIO` + `TEXT` | **refusée** (1007) |
| `AUDIO` + transcription de sortie | **fonctionne** — texte obtenu en 3,1 s |
| Appel d'outil sur `gemini-3.8-live` | **fonctionne** — 0,6 s, arguments corrects |
| Appel d'outil sur `gemini-3.8-live-extended-thinking` | **aucun appel** (0,8 s, `0 function_call`), quel que soit le niveau de réflexion |

**Conséquence architecturale** : le raisonnement passe par des sessions Live en
modalité audio ; le texte affiché vient de la **transcription de sortie**, les
structures (plan, document) des **appels de fonction**. Aucun troisième modèle,
aucun repli.

**Conséquence sur le modèle approfondi** : il ne sait pas appeler d'outil. Dès
qu'une mission exige un outil, c'est le modèle rapide qui planifie. Le modèle
approfondi reste utilisé pour le raisonnement sans outil (question complexe en
vocal). C'est documenté dans `app/agent/live_reasoner.py`, pas contourné.

### 1.2 Ce qui a été retiré

- `gemini-3.8-flash`, `gemini-3.5-flash-lite`, `gemini-3.1-flash-lite` : supprimés
  de la configuration et du code. Aucun chemin de repli.
- `gemini-3.8-flash-tts` : supprimé. La lecture d'un texte passe par le modèle Live.
- `generateContent` : plus aucun appel dans le client de raisonnement.

### 1.3 Preuves d'exécution (après migration)

| Test | Résultat |
|---|---|
| Conversation simple | 7,8 s, réponse correcte, modèle `gemini-3.8-live` |
| Conversation avec outil web | 44,9 s (coût de la boucle d'outils en sessions audio) |
| Mission `code_exec` | **completed**, `144` |
| Mission recherche + document | **completed**, document de **1 914 caractères** |
| Synthèse vocale ponctuelle | audio WAV produit (voix `Charon`), aucun modèle TTS séparé |
| Tests backend | **239 passés, 4 ignorés** (1 test obsolète remplacé) |

### 1.4 Fichiers d'identité

- `config/agent/AGENT.md` créé : cycle d'exécution, interdits, style, multitenant.
- `config/agent/SOUL.md` : **écriture bloquée par une protection du système** (fichier
  d'instruction d'agent). Je ne contourne pas ce garde-fou : le contenu est prêt,
  il doit être créé par vous (ou autorisé explicitement). Idem pour l'injection
  runtime, qui attend ce fichier.

---

## 2. Blocages réels (nécessitent une action de votre part)

### 2.1 Clé Gemini (immédiat)

La fenêtre sécurisée est **ouverte** : https://n8n.streetflexs.store/kwes-google/k/DTJrUMPtO9xug9JwJAue6nN0EYCq-ACo

- valable **60 minutes**, **usage unique** ;
- la clé est chiffrée (`GOOGLE_API_KEY_ENC`), jamais journalisée ;
- le service s'arrête après l'envoi ;
- **révoquez l'ancienne clé** dans Google AI Studio.

### 2.2 Déploiement Docker en production (bloqué)

Le compte de service n'a plus le droit de parler au démon Docker : `docker ps`
répond `permission denied` (le socket est `root:docker`). Le déploiement
conteneurisé demanderait une règle sudo que j'ai moi-même retirée pour raison de
sécurité, et je ne peux pas l'ajouter sans root.

Trois options, à trancher par vous :

1. ajouter `babayaga ALL=(root) NOPASSWD: /usr/bin/docker, /usr/bin/docker compose`
   (le plus simple, mais élargit les droits) ;
2. ajouter un verbe `deploy-compose` à `/usr/local/sbin/kwes-ops` (plus propre,
   nécessite une intervention root de votre côté) ;
3. attendre le nouveau serveur et y déployer directement en Docker avec un compte
   disposant des droits.

En attendant, la production reste servie par systemd (API + worker + sandbox),
ce qui fonctionne et reste réversible.

### 2.3 Application Android native (bloqué sur l'outillage)

Aucun JDK, aucun SDK Android, aucun `gradle` sur la machine. Construire un APK
exige :

- OpenJDK 17 + Android SDK (commande `apt` → **root**) ;
- ou Android Studio sur votre poste ;
- un compte **Google Play Console** (25 $ une fois — dépense, donc votre accord).

Je peux écrire le projet Kotlin complet (VoiceInteractionService, bridge Android,
permissions, build Gradle), mais il ne produira pas d'APK ici sans ces outils.

### 2.4 Isolation RLS (faisable, mais risquée sans fenêtre de test)

Le rôle applicatif `kwes` est **superutilisateur avec `BYPASSRLS`** : les 42
politiques ne s'appliquent pas. Le correctif (rôle `kwes_app` non privilégié,
`FORCE ROW LEVEL SECURITY`, contexte utilisateur par transaction) touche toutes
les requêtes. Je ne l'applique pas à l'aveugle sur la base de production : il faut
une fenêtre de test et un rollback validé. Dites-moi quand je peux l'exécuter.

---

## 3. Ce que vous devez fournir (liste complète)

### Immédiat

| Élément | Où | Remarque |
|---|---|---|
| **Nouvelle clé Gemini** | fenêtre sécurisée ci-dessus | puis révoquer l'ancienne |
| Décision Docker (option 1, 2 ou 3) | §2.2 | sinon la prod reste en systemd |

### Android / Play Store

| Élément | Détail |
|---|---|
| Compte Google Play Console | 25 $ une fois, votre carte |
| Keystore de signature | généré sur votre poste, **jamais** dans le dépôt |
| JDK 17 + Android SDK | installation root ou Android Studio |
| Identifiant de l'application | ex. `com.kwes.agent` (à confirmer) |

### Connexions (OAuth / API)

| Service | Ce qu'il faut | Usage |
|---|---|---|
| **Google (Gmail, Calendar)** | Client OAuth « Web » : `client_id`, `client_secret`, URI de redirection | lecture/création de brouillons, agenda |
| **Telegram** | Jeton de bot + `api_id` / `api_hash` (my.telegram.org) | notifications ; lecture de comptes = MTProto, compte dédié |
| **WhatsApp** | Business Cloud API : `phone_number_id`, jeton permanent, numéro vérifié | envoi uniquement ; l'historique privé n'est **pas** accessible |
| **SMS OTP** | Twilio/Vonage : `account_sid`, `auth_token`, numéro expéditeur | connexion par téléphone |
| **KYC / paiements** | Partenaire licencié (à choisir) : identifiants API, contrat | Kwes Pay, désactivé par défaut |

### Infrastructure

| Élément | Détail |
|---|---|
| Nouveau serveur | IP, utilisateur, clé SSH, lorsque livré |
| Accès base pour la migration RLS | fenêtre de maintenance acceptée |
| Autorisation `SOUL.md` | créer le fichier ou m'autoriser à l'écrire |

---

## 4. Ordre d'exécution proposé ensuite

1. **Clé reçue** → redémarrage, vérification des deux modèles, tests de non-régression.
2. **Docker** → image API + worker + compose (Redis, SearXNG), santé, rollback systemd.
3. **RLS** → rôle applicatif, `FORCE RLS`, tests croisés entre deux comptes.
4. **Android** → projet Kotlin, bridge, assistant par défaut, APK signé.
5. **Connecteurs** → Gmail d'abord (lecture + brouillon), puis Telegram, puis SMS.
6. **Kwes Pay** → schéma et états KYC, désactivé par défaut, partenaire ensuite.

Chaque étape sera livrée avec sa preuve d'exécution et son rollback.
