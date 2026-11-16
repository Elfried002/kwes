# ADR-003 — Voix : Gemini Live remplace ElevenLabs

**Date** : 16 novembre 2026 · **Statut** : appliqué et déployé

## Décision

- La conversation vocale utilise **Gemini Live** (`gemini-3.8-live`) en mode
  **serveur à serveur** : le navigateur parle à notre WebSocket, notre serveur
  relaie vers Google. La clé permanente ne quitte jamais le serveur ; aucun
  jeton éphémère n'est nécessaire côté client.
- La synthèse ponctuelle (accueil, prévisualisation des réglages) utilise
  **`gemini-3.8-flash-tts`** via `POST /voice/synthesize`.
- **DeepSeek reste** le moteur de raisonnement (chat, plans, missions). Gemini ne
  remplace pas le raisonnement ; il porte la voix.

## Pourquoi

- ElevenLabs était à 40 000/40 000 de quota jusqu'au 14/12/2026 : voix de
  l'appareil en pratique.
- Gemini Live apporte la reconnaissance, la détection de prise de parole, le
  barge-in et la synthèse dans un seul flux audio natif, sans pipeline
  STT → LLM → TTS.
- Le coût est mesurable (0,005 $/min d'audio entrant, 0,018 $/min sortant).

## Conséquences

- `ELEVENLABS_*` retiré de la configuration et du `.env` ; le fournisseur n'est
  plus instancié nulle part.
- Nouvelle table `voice_sessions` (durée, volume audio, coût estimé) et route
  `GET /voice/usage`.
- La détection de fin de tour est **explicite** : l'API développeur ne clôt pas
  un tour sur un flux continu (constaté le 16/11), le client envoie
  `activity_start` / `activity_end` d'après le niveau du micro.
- Les langues sont décrites par un registre mesuré (`app/voice_languages.py`),
  pas par la documentation du fournisseur.
