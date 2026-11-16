# Plan d'implémentation — Kwes en 72 heures

## Objectif

Livrer une démonstration fonctionnelle et honnête, avec frontend Vercel, backend VPS, DeepSeek, conversation, missions et au moins un parcours d'exécution vérifié. Trois skills sont visés si le temps et les intégrations le permettent.

## Pré-requis bloquants

- VPS acheté et accessible ;
- domaine/DNS disponibles ;
- clés API DeepSeek et ElevenLabs ;
- projet Supabase ;
- dépôt Git ;
- compte Vercel ;
- disponibilité du produit ElevenLabs correspondant au mode choisi.

Si un prérequis manque, réduire le périmètre plutôt que simuler une intégration.

## Jour 1 — Fondation et UX

### Matin
- provisionner VPS ;
- sécuriser SSH et firewall ;
- installer Docker ;
- créer dépôt et structure ;
- créer projet Supabase ;
- préparer variables d'environnement.

### Après-midi
- construire Home et Chat ;
- construire Hybrid Orb ;
- construire Activity ;
- ajouter responsive ;
- déployer Vercel ;
- tester communication frontend/backend avec endpoint health.

### Sortie jour 1
- interface accessible ;
- backend déployé ;
- authentification de base ;
- health check fonctionnel.

## Jour 2 — Intelligence et voix

### Matin
- intégrer DeepSeek via backend ;
- créer conversations et messages ;
- ajouter validation et logs ;
- implémenter tool calling limité.

### Après-midi
- créer task manager ;
- connecter Redis et worker ;
- intégrer ElevenLabs selon API vérifiée ;
- afficher les états vocaux ;
- tester français puis anglais.

### Sortie jour 2
- chat réel ;
- conversation persistante ;
- mission asynchrone ;
- test vocal si fournisseur prêt.

## Jour 3 — Skills, stabilité et démo

### Matin
- `web_research` ;
- `business_planning` ;
- `browser_readonly` si possible ;
- événements de progression ;
- annulation basique ;
- contrôles d'autorisation.

### Après-midi
- tests bout en bout ;
- tests mobile ;
- sécurité ;
- correction des erreurs ;
- répétition du scénario ;
- préparation slides ou fiche de présentation.

## Arbitrage de priorité

P0 :
1. frontend ;
2. backend ;
3. DeepSeek ;
4. conversation persistante ;
5. mission asynchrone ;
6. sécurité minimale ;
7. démonstration stable.

P1 :
- voix ElevenLabs ;
- Orb animé ;
- trois skills ;
- mémoire simple.

P2 :
- langues locales expérimentales ;
- téléphonie ;
- achats ;
- Skill Factory autonome.

Le rendu visuel est important, mais ne doit pas compromettre la stabilité du parcours central.
