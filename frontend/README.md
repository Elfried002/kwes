# Kwes — Frontend

Application web (PWA) de Kwes : React 19 + TypeScript strict + Vite, sans framework UI.
L'Hybrid Orb est un canvas animé piloté par une machine à états déterministe, jamais par le
texte du modèle.

## Démarrage

```bash
cd frontend
npm install
cp .env.example .env        # VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
npm run dev                 # http://127.0.0.1:5173
```

| Commande | Effet |
|---|---|
| `npm run dev` | serveur Vite (127.0.0.1:5173) |
| `npm run build` | `tsc --noEmit` puis build de production dans `dist/` |
| `npm run preview` | sert le build sur 127.0.0.1:4173 |
| `npm run typecheck` | vérification TypeScript stricte |
| `npm test` | Vitest (machine à états + mapping WebSocket) |

Variables : seule `VITE_API_BASE_URL` (non secrète) est exposée au bundle. Aucune clé
DeepSeek / ElevenLabs / Supabase service role ne doit être placée dans une variable `VITE_*`.

## Authentification (dev)

1. `POST {API}/dev/token` avec `{ "email": "..." }` si le backend expose cet endpoint de dev ;
2. sinon, coller un JWT HS256 signé côté serveur avec `DEV_JWT_SECRET`.

Le navigateur ne décode que les claims publics (`sub`, `email`, `exp`) et stocke le jeton dans
`localStorage` (`kwes.session.v1`). Aucun secret de signature n'est présent côté client.
Un `401` efface la session et renvoie à l'écran de connexion.

## Écrans

- **Accueil** : Orb, message d'accueil, envoi réel `POST /chat`, missions actives, état système
  (WS + `GET /health` et dépendances).
- **Chat** : fil, envoi réel, stop (abort), copie, relance, copies de secours et brouillon local.
  Quand le WS est absent, la réponse REST réelle est affichée progressivement et signalée comme
  « affichage progressif local ».
- **Conversations** : liste, création, suppression avec confirmation.
- **Activités / détail** : filtres, progression réelle, étapes, événements WS de la session,
  pause / reprise / annulation selon le statut serveur.
- **Validations** : approbation / refus avec confirmation, hash de charge utile, échéance.
- **Réglages** : langue, voix/dictée, notifications navigateur, intégrations en lecture seule,
  confidentialité, sécurité.

Toute donnée de démonstration renvoyée avec `is_demo` est badgée `[DEMO]`. Aucune donnée fictive
n'est générée par le frontend quand l'API est indisponible : l'écran affiche l'erreur réelle et
conserve le brouillon local.

## Hybrid Orb

- `src/components/orb/orb-state-machine.ts` : table de transitions pure
  (`idle`, `listening`, `thinking`, `executing`, `speaking`, `response`, `success`, `error`,
  `waiting_approval`), issu de `CONTRACTS.md`.
- `src/lib/orb-events.ts` : mapping pur `task.*` / `conversation.*` → événements machine.
- `src/state/KwesProvider.tsx` : connexion WS (backoff 1 s → 30 s + jitter), heartbeat, reprise
  REST à la reconnexion, priorité des validations en attente, retour `success → idle` après 2 s.
- `src/components/orb/HybridOrb.tsx` : particules canvas, écran/portable visible en `executing`,
  glyphes par état, version statique sous `prefers-reduced-motion`, pause quand l'onglet est masqué.

Le GIF de marque (`public/brand/Kwes_Animated_Logo.gif`) est un asset de communication : il n'est
**pas** utilisé comme animation interactive dans le produit.

## PWA

- `public/manifest.webmanifest` (icônes 64/192/512, `theme_color` `#100B32`) ;
- `public/sw.js` : cache de l'app shell, navigation réseau puis cache, assets cache-first,
  routes `/api/` jamais mises en cache ;
- service worker enregistré uniquement en production ;
- `vercel.json` : rewrite SPA + en-têtes de cache.

## Accessibilité

Focus visible, skip link, navigation clavier, labels de formulaire, boutons nommés, contrastes
AA (dégradé d'action assombri pour 4,5:1 avec le texte blanc), état de l'Orb doublé d'un texte
visible et d'une région `aria-live`, `prefers-reduced-motion` respecté, micro activé uniquement
sur action explicite.

## Limites connues

- Le backend n'est pas inclus : sans lui, les écrans affichent des erreurs explicites (aucune
  donnée simulée).
- La synthèse vocale ElevenLabs n'a pas de route dans le contrat P0 ; l'état `speaking` n'est
  déclenché que par une lecture audio réelle.
- Les intégrations ne sont pas exposées par l'API : l'écran Réglages affiche l'absence de route.
- Le streaming est réel via `conversation.delta` ; hors WS, l'affichage progressif est local et
  étiqueté comme tel.
