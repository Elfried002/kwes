# Vercel et PWA — Kwes

## 1. Rôle de Vercel

Héberger le frontend React/Vite et servir les assets statiques. Les tâches persistantes, workers et navigateurs automatisés restent sur le VPS.

## 2. Variables frontend

Seules les variables non secrètes peuvent être exposées au build frontend, par exemple :
- URL publique API ;
- URL publique Supabase si utilisée avec RLS ;
- configuration publique de l'application.

Ne jamais placer les clés DeepSeek, ElevenLabs ou Supabase service role dans une variable `VITE_*`.

## 3. PWA

- manifest ;
- icônes ;
- service worker ;
- cache des ressources statiques ;
- stratégie réseau pour les API ;
- écran hors ligne ;
- versioning du cache.

Les données sensibles et réponses privées ne doivent pas être mises en cache de manière générique.

## 4. Hors ligne

L'utilisateur peut consulter une coquille applicative et des éléments explicitement mis en cache. Les missions ne sont pas exécutées localement : elles continuent sur le VPS lorsqu'elles ont été acceptées par le backend.

## 5. Notifications

Le centre de notifications interne est prioritaire. Les notifications push Web sont une fonctionnalité progressive, dépendante du navigateur, de l'autorisation et de la configuration serveur.

## 6. Microphone

- accès uniquement sur action utilisateur ;
- HTTPS requis ;
- permission navigateur ;
- indicateur micro actif ;
- arrêt explicite ;
- fallback texte ;
- ne pas promettre d'écoute en arrière-plan lorsque la PWA est fermée.

## 7. Déploiement

- connecter le dépôt ;
- définir le root directory `apps/web` si nécessaire ;
- configurer build et output ;
- ajouter les domaines ;
- définir l'URL API ;
- tester CORS ;
- valider PWA sur desktop et mobile.
