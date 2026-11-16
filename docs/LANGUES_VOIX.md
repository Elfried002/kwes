# Langues vocales — mesures et statuts

**16 novembre 2026** · modèle `gemini-3.8-live` · voix `Charon` · sonde : `tools/voice_languages_probe.py`

## Méthode (aucun statut sans mesure)

Pour chaque langue, deux appels réels :

1. **Rendu** : on demande au modèle de prononcer une phrase de référence ; on
   mesure la durée audio et la similarité entre la phrase demandée et la
   transcription de sa propre sortie.
2. **Écoute** : on renvoie cet audio comme entrée d'une seconde session et on
   compare ce que le modèle transcrit.

Les scores sont des similarités de caractères (0–1). Ils mesurent la cohérence du
moteur avec lui-même, pas la qualité perçue par un locuteur : c'est pourquoi une
langue ne passe en « support validé » qu'après relecture par un locuteur natif.

## Résultats mesurés

| Langue | Audio produit | Rendu vs demandé | Écoute (ASR) | Statut |
|---|---|---|---|---|
| Français | 3,6 s | 1,00 | 0,99 | **Validé** (conversation réelle + phrase de test) |
| Anglais | 3,4 s | 1,00 | 0,94 | Expérimental (conversation complète non testée) |
| Swahili | 4,0 s | 1,00 | 0,99 | Expérimental (phrase à valider par un natif) |
| Hausa | 3,5 s | 1,00 | 1,00 | Expérimental (phrase à valider par un natif) |
| Yoruba | 3,7 s | 1,00 | 0,77 | Expérimental — le nom est entendu « Quest », tons non restitués |
| Wolof | 3,3 s | 1,00 | 0,74 | Expérimental — reconnaissance approximative (« Manlaques ») |
| Akan (Twi) | 2,7 s | 0,00 | 0,55 | Expérimental, **ASR non exploitable** (aucune transcription) |
| Baoulé | 3,4 s | n/a (traduction) | 0,15 | Expérimental, **ASR inexploitable** (« 25 de julio ») |
| Dioula | 3,4 s | n/a (traduction) | 0,63 | Expérimental — sortie plausible, écoute partielle |
| Bété | 3,1 s | n/a (traduction) | 0,74 | Expérimental — mélange avec le français |
| Nouchi | 4,4 s | n/a (traduction) | 0,99 | Expérimental — fonctionne (base française) |

### Traces réelles (extraits)

- **Yoruba** : demandé « Báwo ni, èmi ni Kwes, olùrànlọ́wọ́ rẹ. » → dit à
  l'identique → entendu « Bawo ni? Ẹmi ni Quest, oluranlọwọ rẹ. »
- **Wolof** : « Salaam, man la Kwes, jàppaleku sa. » → entendu « salam, Manlaques, Japelekuza »
- **Baoulé** : modèle « N n ti Kwes, aidiéfu ba mun. » → entendu « 25 de julio »
- **Dioula** : modèle « I ni cé, ne bɛ Kwes, i dɛmɛbaga. » → entendu « Inice, nebecues y deme vaga »
- **Nouchi** : « Salut la famille, c'est bibi Kwes… » → entendu « … c'est Bibi **Kwess** »
  (le /s/ final est bien perçu)

## Ce que ces chiffres disent — et ne disent pas

- Le moteur **produit de l'audio** dans toutes les langues testées, y compris
  celles pour lesquelles il n'a pas de bonne reconnaissance.
- La **reconnaissance** est solide en français, anglais, swahili, hausa ; moyenne
  en yoruba et wolof ; inexploitable en twi, baoulé et bété.
- Les phrases des langues ivoiriennes ont été **produites par le modèle**, pas
  par un locuteur : elles doivent être réécrites par des natifs avant d'être
  présentées comme référence.
- Aucune de ces mesures ne remplace une écoute humaine.

## Architecture modulaire (ajouter un moteur STT/TTS)

- `app/voice_languages.py` : registre (code, libellé, statut, ASR, TTS, phrase,
  preuve, validation native). C'est la seule source de vérité pour l'interface.
- `app/agent/gemini_live.py` : moteur de conversation (Gemini Live).
- `app/agent/voice.py` : synthèse ponctuelle (Gemini TTS).
- Remplacer un moteur = fournir un objet qui expose `synthesize()` et
  `list_voices()` (voix) ou `events()/send_audio()` (conversation), puis changer
  la fabrique. Aucun code métier n'appelle un SDK de fournisseur directement.

## Prochaines actions

1. Faire relire les phrases par des locuteurs natifs (sw, ha, yo, wo, tw, bnc,
   dyu, bet) et remplacer celles qui sont fautives.
2. Tester une conversation complète en anglais, swahili et hausa.
3. Décider si le twi/baoulé/bété restent proposés en TTS seule (sans promesse de
   compréhension) ou basculent en « non disponible ».
4. Si la qualité ne suffit pas : brancher un STT dédié (par exemple un moteur
   local fine-tuné) derrière la même interface, sans toucher à l'interface.
