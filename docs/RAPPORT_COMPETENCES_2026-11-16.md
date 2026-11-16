# Kwes — état des compétences

**16 novembre 2026, 21 h 15** · branche `alpha/jour-1` · commit `31d9fcb`
Statuts : **PROD** (en ligne et vérifié) · **TESTÉ** (prouvé hors production) · **PARTIEL** · **ABSENT** · **BLOQUÉ**

## 1. En une phrase

Kwes est un agent personnel qui converse, se souvient, cherche sur le web, lit des pages
(y compris celles qui se construisent en JavaScript), rédige des documents téléchargeables,
planifie et exécute des missions avec progression réelle, et demande ton accord avant toute
action sensible. Il parle aussi à voix haute, s'installe comme application, et tourne en
production sur ton domaine.

## 2. Compétences livrées

| Compétence | Où | Statut | Preuve |
|---|---|---|---|
| Conversation texte, réponse en flux | PWA | PROD | deltas SSE réels, 11 tests dédiés |
| Mémoire persistante (« retiens que… ») | PWA | PROD | 3 faits en base, réinjectés dans les conversations suivantes |
| Documents rédigés et téléchargeables | PWA | PROD | note de 909 caractères téléchargée depuis Chrome, nom de fichier correct |
| Recherche web avec sources | PWA | PROD | appels réels, sources citées, échecs annoncés franchement |
| Lecture de page avec navigateur (JS rendu) | PWA | PROD | Chromium 159 : quotes.toscrape.com/js, Wikipédia Abidjan (population 2021), Hacker News (titres du jour) |
| Planification en étapes + dépendances | PWA | PROD | plan JSON validé, 6 étapes max, repli sûr |
| Missions exécutées en arrière-plan | PWA | PROD | worker réel, progression en %, pause/reprise/annulation |
| Approbation obligatoire avant action externe | PWA + API | TESTÉ | 14 tests de politique ; 0 approbation réelle déclenchée à ce jour |
| Journal d'audit de chaque décision | API | PROD | `audit_logs` alimenté à chaque appel d'outil et chaque étape |
| Voix : synthèse + conversation mains libres | PWA | PARTIEL | moteur codé et testé ; quota ElevenLabs épuisé → voix de l'appareil |
| Comptes : inscription, connexion, mot de passe | PWA | PROD | Supabase Auth, jetons ES256 vérifiés côté API |
| Application installable (PWA) | PWA | PROD | mode installé → ouverture directe sur la connexion |
| Site public (référencement, partage) | Web | PROD | métadonnées, image de partage, `robots.txt`, `sitemap.xml`, données structurées |
| Connecteurs d'appareil (Android, desktop) | API | PARTIEL | enregistrement, jeton dédié, commandes, révocation : backend seulement, aucun client |

## 3. Les cinq compétences du registre

Kwes ne fait pas ce que le modèle sait faire : il fait ce que le registre expose. Ce registre
est la seule autorité, et chaque appel est arbitré par le moteur de politique avant exécution.

| Compétence | Risque | Droits | Ce qu'elle fait | Limite assumée |
|---|---|---|---|---|
| `web_research` | R0 | recherche + lecture web | cherche, lit, synthétise, cite | moteur gratuit (DuckDuckGo + Wikipédia) : peut renvoyer 0 source sur une requête commerciale |
| `browser_readonly` | R0 | lecture navigateur | ouvre une page avec Chromium, exécute le JS, extrait le contenu | lecture seule : aucun clic, aucun formulaire ; domaines limités à la liste autorisée |
| `business_planning` | R1 | écriture locale | structure un plan, des risques, des indicateurs | déterministe, sans accès externe |
| `remember` | R1 | écriture locale | retient un fait durable, sans doublon | pas encore de recherche sémantique (pas d'embeddings) |
| `document_write` | R1 | écriture locale | rédige un document privé, lisible et téléchargeable | texte et markdown uniquement |

## 4. Ce qui est partiel

- **Recherche web** : DuckDuckGo Instant Answer + Wikipédia. Sur « frais Payoneer », 0 source
  renvoyée. Un moteur payant (Brave, Bing, Serper) changerait la donne — décision de coût.
- **Voix** : la synthèse premium (ElevenLabs) est à 40 000/40 000 jusqu'au 14/12/2026. Le
  barge-in est codé et testé en unité, jamais prouvé sur un micro réel.
- **Approbations** : tout le circuit existe (création, validation, rejet, expiration, empreinte
  du contenu), mais aucune action R2 n'a encore été proposée en conditions réelles.
- **Connecteurs d'appareil** : l'API est prête, l'application compagnon n'existe pas.
- **Lecture web** : en production, la liste de domaines autorisés reste fermée
  (Wikipédia, exemple, DuckDuckGo). L'ouverture à tout site public est codée et testée
  (garde-fous SSRF conservés), mais désactivée : c'est un interrupteur, `BROWSER_OPEN_WEB`.

## 5. Ce qui n'existe pas

- Envoi d'e-mails, agenda, rappels planifiés, réseaux sociaux, e-commerce, paiements.
- Dépôt de fichiers par l'utilisateur (le bouton « Joindre » est présent, le backend non).
- Notifications hors application (push), application Android ou iOS native.
- Conversation vocale duplex intégral (parler par-dessus la réponse) : nécessite une API
  temps réel facturée à la minute.
- Recherche sémantique dans la mémoire (colonne vectorielle présente, aucun embedding).
- Pentest / red team : suspendu par contrat, non réactivé.

## 6. Chiffres vérifiés ce jour

- **153** tests backend, **134** tests frontend, typage TypeScript propre, build Vite OK.
- **16** tables, **43** politiques de sécurité par ligne, **36** routes API, **10** écrans.
- Production : application Vercel + API HTTPS (`/kwes-api`), base PostgreSQL, Redis et
  fournisseur LLM tous `ok` au moment du rapport.
- Chromium **159** installé et utilisé ; pages JavaScript rendues (preuves ci-dessus).

## 7. Trois décisions qui débloquent la suite

1. **Ouvrir la lecture web à tout site public** (une variable, réversible) — sans cela, Kwes
   ne peut lire que trois domaines, ce qui rend le navigateur inutile en pratique.
2. **Choisir un moteur de recherche payant** (~5 à 15 € par mois selon le volume) — la
   recherche actuelle est la limite la plus visible pour un usage commercial.
3. **Passer l'API en service système** : elle tourne aujourd'hui comme processus enfant de
   mon gateway. Un redémarrage de l'agent coupe le service.
