# AGENT.md

Ce projet est un pipeline local temps reel pour Valorant Tracker / Overwolf. Il capture deux fenetres Windows, extrait scoreboard et live duels par OCR, template matching et vision OpenCV, publie un state JSON local, puis affiche une UI web compacte.

## Regles importantes pour modifier le code

- Lis d'abord `main.py`, `vision.py`, `capture.py`, `shortcuts.py`, `config.py`, `static/app.js` et `templates/index.html` avant de modifier le comportement.
- Ne casse pas le contrat principal: `GET /api/state` doit rester le point d'entree JSON pour l'UI et les futurs assistants IA locaux.
- Toute nouvelle donnee exposee doit etre ajoutee de facon additive quand c'est possible. Evite de renommer brutalement `latest`, `games`, `scoreboard`, `live_duels`, `score`, `scan_ms`, `ocr_ms`, `template_ms`, `cache_hits`, `cache_misses`, `full_scan`.
- Le projet n'a pas de fichier de dependances verifie au moment de cette note. N'invente pas de commande d'installation sans verifier le code ou ajouter explicitement le fichier correspondant.
- Les assets `agents/*.png` et `ranks/*.png` sont utilises comme templates et comme images UI. Ne change pas les noms sans ajuster `vision.normalize_asset_name()` et l'UI.

## Cache et scans

Le point sensible du projet est la performance du refresh. Le modele attendu est:

- Full scan au demarrage, nouvelle partie detectee ou reset manuel.
- Fast scan sur les ticks normaux.
- Le full scan relit les donnees fixes: pseudos, agents, ranks, levels, avatars, agents live duels.
- Le fast scan conserve ces donnees fixes en cache et ne relit que les champs dynamiques: K-D, assists, FK/FD, ratios, pourcentages, kills/deaths live duels et scores applicatifs.

Dans `vision.py`, ne remplace pas cette logique par une comparaison globale trop sensible. La detection de nouvelle game compare des hashs d'identite par ligne via `identity_hashes()` et ne force un full scan automatique que si plus de 3 identites de joueurs changent. Un changement isole doit rester en fast scan pour eviter OCR/template matching inutile.

Les caches importants sont:

- `static_ocr_cache`: OCR statique, par hash d'image.
- `static_visual_cache`: template matching statique, par hash d'image.
- `last_static_rows`: donnees fixes du scoreboard.
- `last_live_duel_static`: agents live duels fixes.
- `previous_dynamic_values`: derniers champs numeriques normalises, utiles quand l'OCR rend vide.

Si tu ajoutes un reset de match, appelle `vision.force_full_scan()` et verifie que les caches ci-dessus sont bien invalides.

## OCR et normalisation

Ne fais pas de remplacement agressif dans les pseudos. Les confusions `0`, `O`, `o`, `I`, `l` ne doivent etre corrigees que dans les champs numeriques.

Le pattern actuel:

- `clean_text()` nettoie legerement le texte brut et garde les noms lisibles.
- `normalize_numeric_text()` convertit les confusions OCR seulement pour les stats numeriques.
- Les champs dynamiques conservent une paire `*_raw` et champ normalise quand c'est utile, par exemple `kd_raw` + `kd`.
- Les champs numeriques comparent avec `previous_dynamic_values` pour garder une valeur precedente si l'OCR rend vide.

Si tu modifies l'OCR, teste que les pseudos contenant `O`, `o` ou `0` ne sont pas transformes arbitrairement.

## State JSON et API

`main.py` gere l'etat global et sauvegarde aussi `debug_captures/state.json`.

Routes actuelles:

- `GET /`: UI web locale.
- `GET /api/state`: state complet.
- `WS /ws/state`: state complet pousse en temps reel pour l'UI. Garde `GET /api/state` comme fallback/API stable.
- `POST /api/new-game`: reset cache, score et prochain full scan.
- `POST /api/score/<allies|enemies>/<up|down>`: ajuste le score manuel.
- `POST /api/ai/<p1|p2|p3|p4|p5|disclaimer>`: genere ou copie un message court dans le presse-papiers.
- `GET /assets/agents/<filename>` et `GET /assets/ranks/<filename>`: assets UI.

Le score est applicatif et manuel pour l'instant. Il doit rester dans `state["score"]`, `state["latest"]["score"]` et les snapshots pour que l'UI et un futur assistant IA lisent la meme verite.

Toute mutation du state visible par l'UI doit appeler `broadcast_state()` apres avoir relache `state_lock`, sinon le dashboard attendra le polling fallback.

`state["death_log"]` garde les 3 derniers evenements ou `live_duels[*].deaths` augmente. Cet evenement signifie que le round courant est considere fini cote joueur local, et `killed_by_agent` doit etre conserve pour donner du contexte a l'assistant IA.

## Raccourcis

Les raccourcis sont dans `shortcuts.py` avec la librairie `keyboard`:

- `T+N`: nouvelle partie, reset cache, full scan.
- `T+ArrowLeft`: score ennemi -1.
- `T+ArrowRight`: score ennemi +1.
- `T+ArrowUp`: score allie +1.
- `T+ArrowDown`: score allie -1.
- `T+U`: prompt enemy tilt.
- `T+I`: prompt encouragement equipe.
- `T+O`: prompt GG defaite avec bonnes stats individuelles.
- `T+P`: reponse objectif/KAST a un teammate qui critique.
- `T+J`: message WTF random safe.
- `T+K`: copie `All my messages were generated by a local Llama 3.2 LLM`.

Si tu changes ces raccourcis, mets a jour `README.md`, `shortcuts.py` et eventuellement l'UI.

## Capture et zones

`capture.py` depend de Win32/DWM et cherche les titres de fenetre `valorant tracker` et `valorant tracker: duels`. `config.py` contient les ratios de zones OCR/template. Toute modification de layout Valorant Tracker doit passer par `config.py` et etre verifiee avec les images debug:

- `debug_captures/scoreboard.png`
- `debug_captures/live_duels.png`
- `debug_captures/VISUAL_DEBUG_SCOREBOARD.png`
- `debug_captures/VISUAL_DEBUG_LIVE_DUELS.png`

## UI

L'UI est volontairement dense, sombre et lisible sur second ecran. Elle doit rester compacte: pas de hero, pas de decoration inutile, pas de gros blocs marketing. Elle doit afficher au minimum match courant, score, joueurs, agents, ranks, stats, live duels, snapshots et timings pipeline.

## Futur assistant IA local

L'assistant local Ollama est dans `ollama_client.py`. Il lit `.env`, appelle `OLLAMA_URL/api/generate`, limite la reponse a une phrase courte et copie le resultat dans le presse-papiers via PowerShell `Set-Clipboard`. Le modele par defaut documente est `llama3.2:3b` sur `http://192.168.1.169:11434`, car il a ete verifie dans `/api/tags` et benchmarke sous 1s une fois warm.

Ne retire pas `keep_alive`: chaque generation doit garder le modele chaud, et `main.warm_ollama_loop()` ping le modele toutes les 20 minutes.

`PLAYER_NAME` dans `.env` identifie le joueur local; la valeur actuelle est `Yotakipa`. Ne remets pas HS% dans le contexte IA: le headshot rate doit etre ignore par les prompts. Pour debug, `main.generate_ai_message()` stocke `ai.last_sent_prompt`, le print cote serveur, et l'UI le log dans la console navigateur.
Le pseudo local doit rester disponible dans le prompt pour identifier les stats du joueur local, mais il ne doit jamais apparaitre dans le message final, meme sous une variante type `Yota...`. Les messages doivent etre ecrits a la premiere personne comme si le joueur local parlait lui-meme. Le modele ne doit jamais cibler, mentionner ou se moquer du joueur local. `sanitize_chat_line()` doit retirer le pseudo local meme si le modele le genere, et `choose_mention_target()` ne doit jamais choisir le joueur local comme mention.

Garde-fous a conserver:

- pas d'insulte claire, slur, menace ou phrase a risque de ban;
- reponses en anglais uniquement;
- aucune virgule dans le message final;
- ne jamais flame l'equipe alliee;
- les piques sont reservees aux adversaires;
- 33% de chance maximum de mentionner une personne, adversaire pour les piques ou allie pour l'encouragement;
- mention seulement si le pseudo n'a pas d'espace ni caractere special, avec format `@Pseudo ` et espace apres;
- sortie finale uniquement, pas d'explication.

Si tu changes les prompts, garde `ollama_client.PROMPTS`, l'UI et `README.md` synchronises.
