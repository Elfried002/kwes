# KWES — Rapport de validation pré-démonstration

**Date** : 17 novembre 2026 · **Commit audité au départ** : `82934e5` · **Arbre Git** : propre
**Verdict** : **prêt pour une démonstration encadrée**, avec deux réserves explicites : la voix n'a
pas été validée sur un téléphone physique ni par une écoute humaine, et la latence vocale n'est pas
stable en cas de sessions répétées.

Statuts utilisés : **VALIDÉE ET TESTÉE**, **VALIDÉE PARTIELLEMENT**, **NON VALIDÉE**,
**DÉSACTIVÉE PAR SÉCURITÉ**, **BLOQUÉE**.

---

## 1. État initial réel (vérifié, pas supposé)

| Élément | Constat |
|---|---|
| Commit | `82934e5` — `feat(p2-p3): voix mesurée, cœur agentique vérifié, interface simplifiée` |
| Arbre Git | propre (aucun fichier modifié, aucun non suivi) |
| `kwes-api` | actif, `User=babayaga`, `NoNewPrivileges=yes`, `ProtectSystem=strict` |
| `kwes-worker` | actif, **`NoNewPrivileges=yes`** — confirmé sur l'unité installée **et** sur l'unité du dépôt |
| `kwes-searxng` | `Up (healthy)`, `127.0.0.1:8888` |
| `kwes-docker-proxy` | `127.0.0.1:2375`, `CONTAINERS=1 POST=1 VOLUMES=1 EXEC=0` |
| PostgreSQL / Redis | conteneurs sains, non exposés hors réseau Docker |
| HTTPS | `n8n.streetflexs.store`, certificat Let's Encrypt valide jusqu'au **5 janvier 2027** |
| Frontend | alias `frontend-phi-pied-lzumzbngjw.vercel.app` (production, pas une preview) |

**Point sur la commande d'approbation expirée** : elle visait à retirer `NoNewPrivileges` du worker.
Elle n'a jamais été exécutée, et le rapport P2/P3 disait vrai : **le worker conserve
`NoNewPrivileges=true`**. Le worker n'a besoin d'aucun privilège : il parle au runner par socket Unix.

---

## 2. Audit des privilèges

| Compte | Avant | Après |
|---|---|---|
| `babayaga` (services) | `NOPASSWD: ALL` | **`NOPASSWD: /usr/local/sbin/kwes-ops` uniquement** + sudo avec mot de passe |
| `ubuntu` (cloud-init) | `NOPASSWD: ALL` | inchangé — **risque résiduel** (compte de secours, voir §11) |

`kwes-ops` est un point d'entrée fermé (12 verbes : `status`, `health`, `restart-api`,
`restart-worker`, `restart-all`, `logs-api`, `logs-worker`, `logs-sandbox`, `containers`,
`db-stats`, `backup`, `deploy-units`). Aucun argument libre n'atteint un shell ; un verbe inconnu
est refusé.

Vérifications après retrait :

```
$ sudo -n -l
    (root) NOPASSWD: /usr/local/sbin/kwes-ops
$ sudo -n docker ps          → refusé
$ sudo -n cat /etc/shadow    → refusé
$ sudo -n systemctl restart nginx → refusé
$ sudo -n /usr/local/sbin/kwes-ops health → local=200 public=200
```

### 2.1 Faille réelle trouvée sur le proxy Docker

Le proxy filtrait les routes mais **pas le contenu des requêtes** :

```
$ curl -X POST http://127.0.0.1:2375/containers/create?name=kwes-audit-risk \
  -d '{"Image":"python:3.12-alpine","HostConfig":{"Privileged":true,"Binds":["/etc:/host-etc:ro"]}}'
{"Id":"4f2698a3…","Warnings":[]}      ← accepted: conteneur privilégié avec /etc monté
```

Tout processus local pouvait donc obtenir un conteneur privilégié avec un montage de l'hôte, soit
la compromission du serveur. Le conteneur a été supprimé immédiatement (jamais démarré).

**Correction** : proxy supprimé, port 2375 fermé. Remplacé par `kwes-sandbox`, un runner root à
socket Unix (`/run/kwes/sandbox.sock`, `0660 root:kwes`) dont le contrat est
`{code, language, timeout}` et qui **construit lui-même** la commande Docker. Aucun paramètre client
n'atteint `docker run` : ni image, ni montage, ni privilège.

Isolation conservée : `--network none`, `--cap-drop ALL`, `--read-only`, `--user 65534:65534`,
`--memory 256m`, `--cpus 0.5`, `--pids-limit 64`, `--tmpfs /tmp:size=32m`, suppression du conteneur
en fin d'exécution, sortie plafonnée à 20 000 caractères.

---

## 3. Tests de sécurité exécutés

| Test | Résultat |
|---|---|
| Accès au proxy Docker depuis un processus local | **n'a plus de cible** : port fermé, conteneur supprimé |
| Conteneur privilégié avec montage hôte | impossible : le runner construit la commande |
| Lecture d'un fichier de l'hôte depuis le conteneur | `/etc/kwes-secret` → `False` |
| Réseau depuis le conteneur | `URLError` (aucune route) |
| Exécution prolongée (boucle infinie) | tuée à 3 s, conteneur supprimé |
| Dépassement mémoire / CPU | limites `256m` / `0.5` appliquées par le démon |
| Socket accessible à un autre utilisateur | `0660 root:kwes` ; groupe `kwes` = babayaga uniquement |
| Permissions du worker | `NoNewPrivileges=yes`, `ProtectSystem=strict`, `ProtectHome=read-only` |
| Isolation entre utilisateurs | 404 inter-utilisateurs, `user_id` filtré, 42 politiques RLS |
| `code_exec` de bout en bout | mission `completed`, `3.12.16 / 42`, exit 0 |

Commande de test du socket par un compte hors groupe : refusée par le noyau (mode 0660).

---

## 4. Routeur Gemini — correction du mode « collé »

**Deux défauts trouvés, tous deux corrigés :**

1. **Le mode approfondi restait actif** après son déclenchement (défaut signalé).
2. **La bascule automatique détruisait la réponse en cours** : changer de modèle annule la pompe
   de la session, donc la réponse en préparation. Preuve : le test navigateur est passé de
   « audio réel reçu et joué » (8 buffers) à « aucun audio joué » après activation de l'auto-bascule.

**Décision** : l'auto-bascule est **désactivée par défaut** (`voice_auto_thinking=false`). Le mode
approfondi s'active explicitement (`{"type":"mode","value":"thinking"}`) et **revient seul au mode
rapide dès la fin de la réponse** (`revert_pending` → `fin_reponse`).

Transitions mesurées :

```
départ: fast
mode -> thinking | client        | gemini-3.8-live-extended-thinking
mode -> fast     | fin_reponse   | gemini-3.8-live
```

Contexte conservé (6 derniers échanges réinjectés), repli automatique si le modèle approfondi est
indisponible, aucun double appel.

**Statut : VALIDÉE ET TESTÉE** pour la non-persistance et les transitions ; **VALIDÉE PARTIELLEMENT**
pour le routage automatique, volontairement désactivé pour ne pas perdre de réponses.

---

## 5. Voix — mesures et validations

| Élément | Résultat |
|---|---|
| Test navigateur (micro simulé Chromium) | **8 buffers, 2,62 s d'audio joués**, 0 erreur console |
| TTFB (échantillon du matin, 6 tours) | P50 **915 ms**, P95 **989 ms** |
| TTFB (échantillon du soir, 10 tours) | P50 **842–1054 ms**, un pic à **3,6 s**, un à **11,3 s**, **1 échec sur 6** |
| Compréhension du français (6 formulations) | **95,2 %** normalisée, 92,0 % brute |
| Prononciation | règle `/kwes/` (« Kwéss ») ; F1 mesuré 539 Hz (indicatif) |
| Écoute humaine | **NON VALIDÉE** — aucun panel n'a écouté les échantillons |
| Téléphone physique | **NON VALIDÉE** — aucun test sur appareil réel |

La latence se dégrade quand les sessions s'enchaînent : même code, même serveur, P95 instable
(0,99 s le matin, 3,6–11,3 s en fin de journée). C'est côté fournisseur, pas côté Kwes. **À
considérer comme un risque de démonstration** : prévoir une session de chauffe et un repli texte si
aucun son n'arrive en 3 s.

Le seuil VAD de 380 ms n'a **pas** été modifié : aucun test ne démontre un problème, et le
raccourcir davantage couperait les pauses naturelles.

---

## 6. Scénarios de démonstration

### Scénario A — recherche approfondie (cybersécurité en Côte d'Ivoire)

Mission `72378433-4e9b-418b-9b06-8980d0d616ac` → **completed**

- 3 requêtes planifiées, 5 sources trouvées, **3 lues et enregistrées comme preuves**.
- Sources officielles : `gcpnd.gouv.ci`, `anssi.gouv.ci`, `itu.int`.
- Synthèse citée `[1] …` rattachée aux extraits réellement lus.
- Statut : **VALIDÉE ET TESTÉE**.

### Scénario B — production documentaire

Mission `eb2c5ac6-085f-46be-bde9-7f57cc3f9664` → **completed**

- `web_research` → `document_write` avec `source_step` : le document reprend les sources lues.
- **4/4 sources lues**, document de **1 857 caractères** avec section « Sources consultées ».
- Téléchargement authentifié vérifié (`GET /documents/{id}/download`).
- Statut : **VALIDÉE ET TESTÉE**.

**Correction apportée** : les documents ne faisaient que ~200 caractères (le planificateur est
limité à 900 jetons). Une étape peut désormais consommer le résultat d'une étape amont
(`source_step`) ; le document est complété par les sources réellement lues, jamais par du texte
inventé.

### Scénario C — mission agentique multi-étapes

Mission `ad9041a4-2524-48ed-8318-73678cfeedb2` → **completed**

- 4 étapes : recherche → `code_exec` (`devis = 900000 FCFA`) → document (1 099 caractères) → mémoire.
- Vérification : 2/2 sources lues, exécution réussie en 550 ms, document présent, fait mémorisé.
- Statut : **VALIDÉE ET TESTÉE**.

### Scénario D — action nécessitant une autorisation

Mission `8d7c74a2-56a4-4657-a3bf-33ef3ac7d75e` → **awaiting_approval** (aucune exécution)

- `publish_external: true` → approbation créée, mission en attente, rien n'est publié.
- Statut : **VALIDÉE ET TESTÉE**.

### Outil inconnu

`email_send` → **refusé à la validation du plan** (`VALIDATION_ERROR`), aucun appel d'outil.
Statut : **VALIDÉE ET TESTÉE**.

---

## 7. Non-régression

| Suite | Référence | Résultat |
|---|---|---|
| Backend (avec sandbox) | 243 | **244 passed** en 77,84 s |
| Frontend | 134 | **134 passed** |
| Build frontend | OK | `built in 4.20s` |
| Scan de secrets | 0 | **0 occurrence** |

Aucun test supprimé ni affaibli ; un test ajouté (runner absent → erreur explicite).

---

## 8. État du déploiement

| Élément | État |
|---|---|
| API | active, `/api/v1/health` → 200 local et public |
| Worker | active, `NoNewPrivileges=yes` |
| Sandbox runner | active, socket `0660 root:kwes` |
| Redis / PostgreSQL | sains, non exposés |
| SearXNG | healthy, `127.0.0.1:8888` |
| Proxy Docker | **supprimé**, port 2375 fermé |
| Frontend | production Vercel, alias stable |
| HTTPS | Let's Encrypt, expire le 5 janvier 2027 |
| Base | 31 missions, 38 preuves, 9 documents, 4 mémoires, 8 profils, 42 politiques RLS |

---

## 9. Anomalies restantes

| # | Anomalie | Gravité | Statut |
|---|---|---|---|
| 1 | TTFB P95 instable (3,6 s puis 11,3 s, 1 échec/6) en sessions répétées | **élevée pour une démo** | ouverte — fournisseur |
| 2 | Voix non testée sur téléphone physique | élevée | **NON VALIDÉE** |
| 3 | Prononciation non validée à l'oreille | moyenne | **NON VALIDÉE** |
| 4 | Le nom est parfois omis ou transcrit « Kwezi » | faible | ouverte |
| 5 | Documents issus du planificateur courts sans `source_step` | moyenne | partiellement corrigée |
| 6 | `ubuntu` conserve `NOPASSWD: ALL` | élevée | **risque résiduel assumé** |
| 7 | Mode approfondi non exposé dans l'interface | moyenne | à ajouter |
| 8 | Pas d'audit d'accessibilité formel | moyenne | ouverte |

---

## 10. Risques résiduels

1. **Latence vocale variable** : la démonstration doit prévoir une chauffe et un repli texte.
2. **Compte `ubuntu` en `NOPASSWD: ALL`** : compte de secours créé par cloud-init. Le retirer sans
   accès console au fournisseur pourrait verrouiller l'administration ; **décision d'Elfried**.
3. **Runner root** : il exécute une commande Docker fixe, mais reste un service root. Compromettre
   le runner (`/usr/local/sbin/kwes-sandbox-runner`, root:root 0755, non modifiable par babayaga)
   équivaudrait à root.
4. **SearXNG** dépend de moteurs tiers ; une panne généralisée dégrade la recherche.
5. **Sans téléphone réel**, le comportement du micro mobile (écho, gain automatique, Bluetooth)
   reste inconnu.

---

## 11. Procédures de rollback

**Retour à un sudo large (si l'exploitation est bloquée)** — nécessite un accès root hors agent :

```bash
echo 'babayaga ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/babayaga
chmod 0440 /etc/sudoers.d/babayaga && visudo -c
```

**Retour au proxy Docker** (déconseillé : faille démontrée) : redémarrer le conteneur
`tecnativa/docker-socket-proxy` sur 127.0.0.1:2375 et remettre l'ancien `code_exec`.

**Désactiver `code_exec`** :

```bash
sudo systemctl stop kwes-sandbox && sudo systemctl disable kwes-sandbox
# puis retirer code_exec de backend/app/skills/ (ou du manifeste) et redémarrer le worker
```

**Désactiver la voix approfondie** : `voice_auto_thinking=false` (déjà par défaut) ;
`GOOGLE_LIVE_THINKING_MODEL` inchangé.

**Code** : `git revert 82934e5..HEAD` puis `sudo /usr/local/sbin/kwes-ops restart-all`.

---

## 12. Verdict par fonctionnalité

| Fonctionnalité | Statut |
|---|---|
| Authentification ES256 / refus HS256 | VALIDÉE ET TESTÉE (P0.1, non modifiée) |
| Recherche multi-fournisseurs + preuves | VALIDÉE ET TESTÉE (scénario A) |
| Documents + téléchargement authentifié | VALIDÉE ET TESTÉE (scénario B) |
| Mission multi-étapes + vérification | VALIDÉE ET TESTÉE (scénario C) |
| Approbation des actions sensibles | VALIDÉE ET TESTÉE (scénario D) |
| Refus d'outil inconnu | VALIDÉE ET TESTÉE |
| Exécution de code isolée | VALIDÉE ET TESTÉE (via runner, après correction d'une faille) |
| Retour du mode approfondi au mode rapide | VALIDÉE ET TESTÉE |
| Routage automatique du mode | VALIDÉE PARTIELLEMENT — désactivé pour ne pas perdre de réponses |
| Voix en navigateur | VALIDÉE ET TESTÉE (micro simulé) |
| Voix sur téléphone physique | **NON VALIDÉE** |
| Prononciation « Kwéss » perçue | **NON VALIDÉE** (mesure instrumentale seulement) |
| Sandbox rootless | **BLOQUÉE** (namespaces utilisateur désactivés sur le noyau) |
| Privilèges sudo du compte de service | VALIDÉE ET TESTÉE (réduits à `kwes-ops`) |
| Compte `ubuntu` | **BLOQUÉE** — décision d'Elfried requise |

---

## 13. Ce qu'il reste à faire avant une démonstration publique

1. Faire écouter 3 réponses vocales par deux personnes francophones (prononciation du nom).
2. Tester sur un téléphone réel : micro, haut-parleur, Bluetooth, réseau mobile.
3. Répéter les scénarios A et C juste avant la démo, avec une session vocale de chauffe.
4. Décider du sort du compte `ubuntu`.
5. Ajouter le bouton « réflexion approfondie » dans l'écran vocal.
