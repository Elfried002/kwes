# Référence « Dots » — ce qu'on en tire, ce qu'on n'en prend pas

Étude du 16/11/2026 · sources : page officielle `openai.com/index/introducing-dots/` (HTML fourni par Elfried) + presse spécialisée.

## Ce qu'est Dots (faits vérifiés)
- Agents annoncés le **29 septembre 2026** par OpenAI, réservés aux offres payantes de ChatGPT.
- Modèle **GPT-6 Astra**, exécution sur **leur propre ordinateur cloud**, capable de continuer à travailler **entre deux conversations** (d'où le nom : des points qui restent actifs).
- Répondent aussi au téléphone et se connectent à des applications.

## Ce que montre le code de la page
- **Typographie** : `OpenAI Sans` en trois graisses (Regular / Medium / Bold), servie en woff2 depuis leur CDN. Interdite à la réutilisation — on garde **Sora** (titres) + **Instrument Sans** (texte), qui remplissent le même rôle : graisse franche, interlettrage serré sur les gros titres, corps très lisible.
- **Aucune `@keyframes`** dans la page : tout le mouvement est piloté en **JavaScript** (transitions d'état, pas d'animations CSS déclaratives). Conséquence pour nous : les micro-mouvements doivent être **pilotés par l'état réel**, pas par des boucles décoratives.
- **Mise en page** : grille **bento** (tuiles de tailles inégales), captures produit réelles dans des cadres sobres, beaucoup de blanc, une seule idée par tuile.
- **Marque** : un simple « o » (`dots-o-updated.svg`) — un point. La personnalité est portée par les personnages, pas par le logo.
- **Personnages** : blobs organiques, matière mate et granuleuse, bords irréguliers, **un accessoire** (béret, lunettes, nœud papillon) et deux yeux. Rien de plus.

## Ce que Kwes adopte
1. Un **seul objet lumineux** par écran, jamais plusieurs.
2. Un **personnage** simple : forme organique, deux yeux expressifs, **un** accessoire signature (anneau lumineux propre à Kwes).
3. Un **mouvement piloté par les événements** du backend (aucune animation qui simule une activité inexistante).
4. Une **grille bento** sur la page publique, avec de vraies captures de l'application.
5. Un espacement généreux, une hiérarchie typographique franche.

## Ce que Kwes n'adopte pas
- La police OpenAI Sans et tout asset de leur CDN (licence).
- Les personnages eux-mêmes, leurs accessoires et leurs formes exactes.
- Le vocabulaire et la structure de leur page.

## Application concrète
- Écran vocal : fond noir, un blob-personnage centré, trois boutons discrets.
- Accueil : rail d'icônes 72 px, une barre de saisie, rien d'autre.
- Page publique : bento de captures réelles, titres en Sora, corps en Instrument Sans.
