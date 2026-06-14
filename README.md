# Valorant AI Chatbot / Local Tracker Pipeline

Projet genere et maintenu avec Codex. Le code actuel est une application locale pour Valorant Tracker / Overwolf: elle capture les fenetres Tracker, extrait scoreboard et live duels par OCR, template matching et vision OpenCV, expose un state JSON local, puis affiche une UI web compacte pour suivre la partie.

L'objectif produit futur est d'ajouter un assistant IA local, probablement via Ollama avec un modele type Qwen ou Llama, capable de lire le state courant et de commenter la game sans service distant obligatoire.

## Fonctionnalites actuelles

- Capture Windows des fenetres `Valorant Tracker` et `Valorant Tracker: Duels`.
- Parsing scoreboard: joueurs, agents, ranks, levels, K-D, assists, FK/FD, KD ratio, KPR, ESR, KAST, SRV, HS et 1vX.
- Parsing live duels: agent, kills, deaths et diff.
- State JSON local via `GET /api/state`.
- Sauvegarde debug dans `debug_captures/state.json`.
- UI web locale dense sur `http://127.0.0.1:8787`.
- Historique de snapshots par match, limite actuelle de 500 snapshots par game.
- Timings pipeline: total, capture, vision, OCR, template, cache hits/misses, mode full/fast scan et raison du full scan.
- Score manuel allie/ennemi expose dans le state et l'UI.

## Architecture detectee

- `main.py`: serveur Flask, boucle de scan, state global, API locale, gestion nouvelle partie et score.
- `capture.py`: detection/capture Win32 des fenetres Valorant Tracker.
- `vision.py`: OCR EasyOCR, matching OpenCV, caches, parsing scoreboard/live duels, detection d'identite de partie.
- `shortcuts.py`: raccourcis clavier globaux via `keyboard`.
- `config.py`: ratios de zones pour decouper scoreboard et live duels.
- `templates/index.html`, `static/app.js`, `static/app.css`: UI web locale.
- `agents/` et `ranks/`: templates PNG et assets UI.
- `debug_captures/`: sorties runtime/debug, ignorees par Git.

## Full scan, fast scan et cache

Le refresh doit rester rapide. Le comportement attendu est:

- Full scan au demarrage.
- Full scan sur reset manuel ou nouvelle game.
- Full scan automatique seulement si plus de 3 identites de joueurs changent.
- Fast scan dans les autres cas.

Le full scan relit les donnees fixes: pseudos, agents, ranks, levels, avatars et agents live duels. Le fast scan garde ces donnees en cache et relit seulement les donnees dynamiques: K-D, assists, stats scoreboard, kills/deaths live duels et score applicatif.

La detection de nouvelle partie repose sur des hash visuels d'identite par ligne dans `vision.identity_hashes()`. Si `changed_identity_count()` detecte plus de 3 lignes changees, le cache statique est reconstruit. Sinon le pipeline conserve `last_static_rows` et evite l'OCR/template matching couteux.

## OCR et confusions 0/O/o

Le code evite les corrections agressives dans les pseudos. Les conversions `O`/`o` vers `0` et `I`/`l` vers `1` sont appliquees seulement aux champs numeriques via `normalize_numeric_text()`.

Pour les stats dynamiques, le state conserve quand possible la valeur brute OCR et la valeur normalisee, par exemple `kd_raw` et `kd`. Si l'OCR rend vide, le pipeline peut reutiliser la derniere valeur numerique connue du meme champ.

## Raccourcis clavier

- `T+N`: force nouvelle partie, reset cache, reset score et full scan.
- `T+ArrowLeft`: diminue le score ennemi.
- `T+ArrowRight`: augmente le score ennemi.
- `T+ArrowUp`: augmente le score allie.
- `T+ArrowDown`: diminue le score allie.

Le score est gere par l'app pour l'instant. Il est visible dans `state.score`, `state.latest.score`, les snapshots et l'UI.

## API locale

- `GET /api/state`: retourne tout l'etat courant.
- `POST /api/new-game`: demande un reset nouvelle partie avec full scan.
- `POST /api/score/allies/up`: score allie +1.
- `POST /api/score/allies/down`: score allie -1.
- `POST /api/score/enemies/up`: score ennemi +1.
- `POST /api/score/enemies/down`: score ennemi -1.
- `GET /assets/agents/<filename>`: sert les images agents.
- `GET /assets/ranks/<filename>`: sert les images ranks.

Modification API documentee: le state inclut maintenant `score`, `latest.score`, `identity_changes` et `full_scan_reason`. Les champs `*_raw` peuvent apparaitre sur les stats OCR dynamiques pour distinguer OCR brut et valeur normalisee.

## Installation et lancement

Commande de lancement verifiee avec l'environnement virtuel present dans ce dossier:

```powershell
.\.venv\Scripts\python.exe main.py
```

Le serveur demarre sur:

```text
http://127.0.0.1:8787
```

Il n'y a pas de `requirements.txt` verifie dans ce dossier au moment de cette documentation. La `.venv` locale contient notamment Flask, EasyOCR, Torch, OpenCV, NumPy et keyboard, mais une procedure d'installation reproductible reste a formaliser.

Important: `vision.ensure_reader()` exige actuellement un GPU CUDA (`torch.cuda.is_available()`), sinon le scan OCR leve `SystemError("GPU absent.")`.

## Debug

Pendant l'execution, le projet ecrit dans `debug_captures/`:

- `scoreboard.png`
- `live_duels.png`
- `VISUAL_DEBUG_SCOREBOARD.png`
- `VISUAL_DEBUG_LIVE_DUELS.png`
- `state.json`

Ces fichiers servent a verifier les zones de crop, les timings et le contenu JSON. Ils sont ignores par Git.

## Limites connues

- Projet Windows-only pour la capture, car `capture.py` utilise Win32, GDI et DWM.
- Pas de fichier de dependances/versioning Python verifie.
- OCR EasyOCR configure en anglais seulement.
- GPU CUDA obligatoire dans le code actuel.
- Les zones de `config.py` dependent fortement du layout Valorant Tracker.
- Le score n'est pas encore extrait automatiquement depuis Valorant Tracker; il est manuel.
- La detection de nouvelle game repose sur des hashs visuels et peut necessiter ajustement si le layout ou la resolution change beaucoup.

## Pistes futures

- Ajouter un fichier de dependances verifie et des instructions d'installation reproductibles.
- Exposer un schema JSON versionne pour `GET /api/state`.
- Ajouter un assistant local Ollama/Qwen/Llama lisant `/api/state`.
- Ajouter des tests unitaires sur `normalize_numeric_text()`, `changed_identity_count()` et la forme du state.
- Rendre le mode CPU possible pour debug hors GPU.
- Ajouter une calibration UI des zones au lieu de modifier seulement `config.py`.
