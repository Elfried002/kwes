# Design system — Kwes

## 1. Direction

Minimalisme immersif inspiré des interfaces d'agents personnels. Ne pas reproduire les marques, logos ou composants propriétaires d'autres produits.

## 2. Couleurs

| Token | Valeur | Usage |
|---|---|---|
| `bg` | `#090D14` | fond principal |
| `surface` | `#111824` | panneaux |
| `surface-raised` | `#192435` | éléments surélevés |
| `blue` | `#78AEFF` | action principale |
| `blue-light` | `#A9D2FF` | accent |
| `text` | `#F4F7FC` | texte principal |
| `muted` | `#9AAAC0` | texte secondaire |
| `success` | `#38B987` | succès |
| `warning` | `#E8B65C` | avertissement |
| `danger` | `#E66D78` | erreur |

## 3. Typographie

Police principale : Geist Sans. Alternative : Inter.

Hiérarchie :
- H1 : 32–40 px desktop, 28–32 px mobile ;
- H2 : 24–28 px ;
- H3 : 18–20 px ;
- body : 14–16 px ;
- metadata : 12–13 px.

Éviter les textes très petits pour les statuts critiques.

## 4. Formes et surfaces

- rayons modérés ;
- bordures fines ;
- ombres discrètes ;
- peu de cartes ;
- espace négatif généreux ;
- contraste suffisant.

## 5. Hybrid Orb

L'Orb est un élément d'identité et un indicateur d'état.

Composition :
- forme sphérique ;
- particules distribuées autour d'un volume ;
- dégradés bleu/blanc ;
- lumière volumétrique ;
- mouvement organique.

Ne pas utiliser une animation lourde qui pénalise le mobile. Prévoir une version statique de repli.

## 6. États visuels de l'Orb

| État | Mouvement | Libellé |
|---|---|---|
| Idle | respiration lente | Prêt |
| Listening | pulsation réactive | Écoute |
| Thinking | particules internes | Réflexion |
| Executing | flux plus actif | Exécution |
| Speaking | oscillation audio | Parle |
| Error | animation interrompue / accent danger | Incident |

## 7. Accessibilité

- Contraste WCAG 2.2 AA visé.
- Focus clavier visible.
- Boutons avec labels accessibles.
- Ne pas communiquer un état uniquement par couleur.
- Respecter `prefers-reduced-motion`.
- Sous-titres/transcriptions pour la voix.
- Contrôle utilisateur sur le microphone.

## 8. Motion

- transitions courtes et cohérentes ;
- aucune animation décorative permanente excessive ;
- synchronisation visuelle audio uniquement si la donnée audio est réellement disponible ;
- GIF réservé aux supports et aperçus ; Rive/Lottie ou Canvas pour l'animation interactive.
