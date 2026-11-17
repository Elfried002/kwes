# Kwes — audit du socle agentique et de la réactivité

**Date** : 18 novembre 2026 · **Commit** : `c75d0ac` · **Méthode** : exécution réelle,
pas de revue de code seule. Chaque affirmation ci-dessous a une sortie d'exécution.

---

## 1. Verdict

| Question | Réponse |
|---|---|
| Le socle agentique fonctionne-t-il ? | **Oui pour 6 compétences réelles**, non pour ce qu'un assistant complet doit faire (e-mail, WhatsApp, agenda, paiements). |
| L'agent a-t-il accès à Internet ? | **Oui** : recherche auto-hébergée + lecture de pages réelles, y compris rendues en JavaScript. |
| Peut-il « taper des commandes » ? | **Dans un conteneur isolé uniquement** : pas de shell sur le serveur, pas de réseau, pas de fichiers de l'hôte. C'est un choix, pas une limite technique. |
| Est-il réactif ? | **Oui en vocal** (694 ms médian avant le premier son), **oui en texte simple** (1,1–1,8 s), **non pour une recherche complète** (14 s). |
| Coupe-t-il la parole quand on reprend la main ? | **Oui, prouvé** : interruption à 1,5 s, zéro bloc audio ensuite. |
| Isolation entre utilisateurs ? | **Oui au niveau de l'API**, **non au niveau de la base** : le rôle applicatif contourne les politiques RLS. |

---

## 2. Ce que l'agent sait réellement faire

Exécution directe des skills par le registre, avec un contexte utilisateur réel :

| Compétence | Résultat mesuré |
|---|---|
| `web_research` | **9,0 s**, 2 sources trouvées et **lues** (RFI, prix du cacao 2026-2027), synthèse citée, fournisseur `searxng` |
| `browser_readonly` | **3,4 s**, page `quotes.toscrape.com/js` (rendue en JavaScript) → 1 521 caractères, 5 citations extraites, titre lu |
| `code_exec` | **2,7 s**, Python **3.12.16**, utilisateur `65534`, réseau **inexistant** (`OSError`), calcul correct (`285`), `sandbox=docker-ephemeral-via-runner`, `network=none` |
| `document_write` | Document de **3 281 caractères** produit par une mission, section « Sources consultées » incluse |
| `remember` | 5 faits persistés, dédoublonnés par utilisateur |
| `business_planning` | Utilisé dans les plans ; ne produit aucune action externe |
| Missions de bout en bout | 2 missions `completed` aujourd'hui : `code_exec` (résultat 391) et `web_research` + `document_write` |

**Ce que cela veut dire concrètement** : Kwes peut chercher, lire, retenir, calculer,
rédiger et enchaîner ces étapes. Ce n'est pas une démonstration simulée : les pages sont
réellement récupérées et les sources citées correspondent aux URL lues.

---

## 3. Ce que l'agent ne sait pas encore faire

Rien de tout cela n'existe aujourd'hui — à ne pas annoncer :

- envoyer ou lire des **e-mails** ;
- **WhatsApp, Telegram**, SMS : aucune connexion ;
- **ouvrir des applications** du téléphone (nécessite une app native Android + accessibilité) ;
- **agenda** (Google Calendar) ;
- **payer des factures** : aucune intégration de paiement, aucune autorisation bancaire ;
- **terminal sur le serveur** : volontairement impossible — le code tourne dans un conteneur sans réseau ni volume de l'hôte ;
- navigation authentifiée (connexion à un site avec identifiants) ;
- OCR de documents, indexation de fichiers.

---

## 4. Réactivité — mesures

### Voix (Gemini Live, mode rapide, 4 tours réels)

| Indicateur | Valeur |
|---|---|
| Temps avant le premier son (médiane) | **694 ms** |
| 95e percentile | **974 ms** |
| Minimum / maximum | 573 ms / 974 ms |
| Tours réussis | **4 / 4** |

C'est le délai entre la fin de la phrase de l'utilisateur et le premier paquet audio
de Kwes. En dessous d'une seconde, la conversation paraît naturelle.

### Texte

| Cas | Temps total |
|---|---|
| Salutation simple | **1,75 s** |
| Question de vulgarisation | **1,17 s** |
| Calcul horaire | **1,07 s** |
| Recherche web avec sources | **14,2 s** |

La recherche complète reste lente : elle enchaîne planification, requêtes, lecture de
pages et rédaction. C'est acceptable en mission, trop lent dans une conversation.

### Barge-in (interruption)

Test réel sur le WebSocket vocal : réponse longue demandée, puis prise de parole
simulée après 12 blocs audio.

```
premier audio à 0,92 s
blocs audio avant interruption : 12
événement interrupted : oui, à 1,50 s
blocs audio reçus après interruption : 0
```

Le serveur coupe la génération, le client vide sa file de lecture. **L'utilisateur
reprend la main immédiatement.**

### Gestes pendant la parole

Mesures dans le navigateur, phase `speaking` :

- bouche : `scaleY` animé entre 0,876 et 0,775 sur 220 ms — elle suit le niveau audio réel (`--level`), pas une boucle factice ;
- mains : rotation/translation actives ;
- halo : animation propre ;
- états distincts : repos, écoute, réflexion (bulle « ? »), exécution (anneau), succès, approbation, erreur.

Limite : mesuré en navigateur, pas encore sur un téléphone physique avec un vrai micro.

---

## 5. Isolation multi-tenant

### Ce qui est vérifié

- **9 utilisateurs**, **49 missions**, 5 utilisateurs distincts en base.
- Requête d'une mission appartenant à un autre utilisateur via l'API : **404 NOT_FOUND**.
- Liste des missions de l'utilisateur courant : **40** sur 49 — aucune fuite visible.
- **16 tables** avec RLS activé, **42 politiques** en base.
- Les endpoints filtrent par `user_id` ; les documents et mémoires sont également privés.

### Le risque à corriger avant le Play Store

Le rôle PostgreSQL utilisé par l'application est **superutilisateur avec `BYPASSRLS`** :
les politiques RLS existent mais **ne s'appliquent pas** à la connexion de Kwes. Aucune
table n'a `FORCE ROW LEVEL SECURITY`.

Autrement dit : l'isolation repose aujourd'hui **uniquement sur le code applicatif**.
Un seul `WHERE user_id = …` oublié dans une future route expose les données d'un autre
compte. Pour un SaaS public, c'est insuffisant.

**Correctif recommandé** (non appliqué, il touche la base de production) :

1. créer un rôle `kwes_app` **non superutilisateur**, sans `BYPASSRLS` ;
2. `ALTER TABLE … FORCE ROW LEVEL SECURITY` sur les 16 tables ;
3. politiques basées sur `current_setting('app.user_id')`, positionné au début de chaque transaction ;
4. garder un rôle séparé pour les migrations.

---

## 6. Modèles Gemini utilisés

| Usage | Modèle | Configuration |
|---|---|---|
| Conversation vocale rapide | `gemini-3.8-live` | voix `Charon`, session 900 s, inactivité 45 s |
| Tâche vocale complexe | `gemini-3.8-live-extended-thinking` | `ThinkingLevel.HIGH`, bascule explicite, retour automatique au mode rapide |
| Synthèse vocale ponctuelle | `gemini-3.8-flash-tts` | utilisée quand une phrase doit être prononcée hors session Live |
| Raisonnement et outils (texte) | `gemini-3.8-flash` | réflexion `LOW` en conversation, `HIGH` en planification |
| Repli de disponibilité | `gemini-3.5-flash-lite`, puis `gemini-3.1-flash-lite` | uniquement sur 429/503, repos de 2 min par modèle |

Un seul appel de modèle par message : la profondeur de réflexion change, le modèle
principal ne tourne jamais en parallèle avec le modèle approfondi.

---

## 7. Défauts trouvés pendant cet audit (corrigés)

1. **`code_exec` était cassé en production.** Les services n'avaient pas le groupe
   `kwes` : le socket du bac à sable (`0660 root:kwes`) refusait la connexion. Le skill
   fonctionnait en ligne de commande, pas depuis l'API ni le worker. → `SupplementaryGroups=kwes`
   ajouté aux deux unités.
2. **Le planificateur produisait des entrées vides.** Le schéma de sortie était figé :
   Gemini n'émet que les propriétés déclarées, donc `code`/`language` (code_exec),
   `url`/`max_chars` (browser) ou `fact` (remember) n'arrivaient jamais. → schéma
   construit dynamiquement à partir des skills installés.
3. **Un document sans texte faisait échouer toute la mission.** → rattaché à l'étape de
   recherche quand elle existe, sinon retiré du plan.

---

## 8. Priorités proposées

1. **Isolation base de données** (rôle applicatif + `FORCE RLS`) — bloquant pour un SaaS multi-tenant.
2. **Connexions de messagerie** (Gmail lecture/brouillon, Telegram) — c'est ce qui transforme
   l'assistant en agent utile au quotidien.
3. **Latence des recherches** : 14 s est trop long en conversation ; viser un retour parlé
   immédiat (« je cherche… ») puis la synthèse.
4. **Test sur téléphone physique** : micro, écho, Bluetooth, réseau mobile — non validé à ce jour.
5. **Application Android** : le Play Store exige l'app native pour les intégrations
   téléphone (notifications, contacts, apps) ; la PWA actuelle ne peut pas les faire.
