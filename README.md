# RecoverIQ

Application web locale (Windows) qui récupère automatiquement vos données Garmin Connect,
les historise dans SQLite et les présente dans un tableau de bord, avec une analyse IA.

> **Avancement**
> - Étape 1 (livrée) : authentification Garmin, import historique, synchronisation quotidienne, stockage, journal.
> - Étape 2 (livrée) : tableau de bord (accueil, indicateurs, charge, activités, corrélations, exports CSV).
> - Étape 3 (livrée) : analyse IA multi-fournisseurs (Anthropic, OpenAI, Gemini, Mistral, serveur compatible OpenAI).

---

## Prérequis

- Windows 10/11
- Python 3.11 ou plus récent (python.org ou gestionnaire `py install` recommandés).
- Un compte Garmin Connect

## Installation

Ouvrez PowerShell dans le dossier du projet :

```powershell
py -3.14 -m venv .venv      # ou toute version >= 3.11
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

Pour le développement (tests) : `pip install -e ".[dev]"`.

## Lancement

Double-cliquez sur **`run.bat`**, ou lancez :

```powershell
.\.venv\Scripts\python.exe -m recoveriq
```

Ouvrez ensuite <http://localhost:8765>. Pour arrêter le serveur, fermez la fenêtre ou faites `Ctrl+C`.

Le serveur écoute uniquement sur `127.0.0.1` : l'application n'est pas exposée sur le réseau.

### Premier lancement

1. Saisissez votre e-mail et votre mot de passe Garmin dans le bloc **Connexion Garmin**.
2. Si Garmin demande un code de vérification (MFA), un champ s'affiche pour le saisir.
3. Deux travaux démarrent ensuite automatiquement :
   - une **synchronisation** des derniers jours ;
   - l'**import historique**, du plus récent au plus ancien, depuis la date de votre première activité.

L'import historique peut durer plusieurs heures : environ 5 appels par jour d'historique, avec une
pause de 1,5 s entre deux appels, soit environ 4 h pour 5 ans (plus 2 appels par jour pour le détail
de la FC et du stress de la journée, que Garmin ne fournit que sur les 4 à 5 derniers mois). Il est **reprenable** : si vous fermez
l'application, il repart là où il s'était arrêté au lancement suivant. La progression s'affiche dans
la page.

### Tableau de bord

| Vue | Contenu |
|---|---|
| **Accueil** | Cartes du jour : Body Battery, VFC, Training Readiness, sommeil, stress. Chaque valeur est comparée à la moyenne des 30 jours précédents, avec son écart et l'évolution sur 14 jours |
| **Indicateurs** | Une courbe par indicateur (30 séries) : valeurs, moyennes mobiles 7 j et 28 j, bande de normalité, statistiques et tendance. En fond, les plages de couleur Garmin quand elles existent : statut VFC (selon la ligne de base personnelle du jour), catégories VO2 max (selon l'âge et le sexe du profil Garmin), score de sommeil, Training Readiness, stress, Body Battery, charge aiguë et ratio aiguë / chronique. Un clic sur une mesure (point bleu) ouvre son détail |
| **Détail d'un jour** | Veille, jour et lendemain, avec la montre du jour (celle des activités et, si elle diffère, la montre principale Garmin) : courbes minute par minute tirées des réponses Garmin déjà importées (FC, stress et Body Battery sur 24 h ; VFC, SpO2, respiration et phases pendant le sommeil). Garmin ne fournit ce détail que pendant environ 4 à 5 mois : il est conservé ici dès qu'il a été synchronisé. Après une mise à jour qui ajoute une série, l'import historique se relance seul au démarrage pour la remonter, activités de ces 3 jours et valeurs journalières de tous les indicateurs |
| **Charge d'entraînement** | Charge aiguë vs chronique, ratio A/C avec zones, focus de charge vs plages cibles, frise du statut, volume hebdomadaire |
| **Activités** | Liste filtrable par type, avec totaux. Un clic sur un en-tête trie la colonne (par défaut : date, plus récente d'abord). La colonne **Récupération** donne le temps de récupération estimé par Garmin juste après la séance : c'est le relevé Training Readiness « après effort » qui suit l'activité (au plus 3 h après la fin et avant l'activité suivante) |
| **Matériel** | Montres ayant enregistré les activités : période d'utilisation, nombre d'activités, durée, distance, D+ et principaux types. Garmin donne l'identifiant de la montre avec chaque activité ; le nom du modèle vient du statut d'entraînement. Certaines activités anciennes n'indiquent aucune montre |
| **Corrélations** | Sommeil vs VFC et Body Battery du lendemain, stress vs recharge nocturne, VO2 max vs volume, semaine vs week-end |
| **Synchronisation** | Connexion Garmin, état de l'import, données reçues par indicateur, journal |

Chaque vue a un sélecteur de période (30 j, 90 j, 1 an, tout) et un bouton **Exporter CSV**.
Sur tous les graphiques temporels : glisser pour se déplacer dans le temps, molette pour zoomer,
double-clic pour revenir à la vue complète (dans le détail d'un jour, les graphiques bougent ensemble).
Dans les vues Indicateurs et Charge d'entraînement, la période fixe la plage affichée au départ et les
statistiques, mais tout l'historique est chargé : on peut glisser au-delà de la période sans zoomer.
Le CSV utilise le séparateur `;` et l'UTF-8 avec BOM : il s'ouvre directement dans Excel.

**Définitions statistiques :**

- **Ligne de base d'un jour J** : moyenne des 30 jours précédents, J exclu, calculée à partir d'au
  moins 10 valeurs. La **bande de normalité** correspond à cette moyenne ± 1 écart type. Une valeur
  hors de la bande est signalée au-dessus ou en dessous de la normale, en vert ou en rouge selon que
  l'écart est favorable ou non.
- **Jours sans mesure** : ils ne sont jamais remplacés par 0 ni interpolés.
- **Datation du sommeil** : le sommeil est daté du jour du réveil. « Sommeil → VFC du lendemain »
  compare la nuit qui se termine le jour J à la VFC et à la Body Battery mesurées ce même matin.
- **Corrélations** :
  - coefficients de Pearson et de Spearman, avec leur p-valeur ;
  - au moins 10 couples de valeurs requis ;
  - pour la comparaison semaine / week-end, test t de Welch et d de Cohen.
- **Zones du ratio aiguë / chronique**, d'après Gabbett (2016) :

  | Zone | Ratio |
  |---|---|
  | Sous-charge | < 0,8 |
  | Optimal | 0,8 – 1,3 |
  | Vigilance | 1,3 – 1,5 |
  | Risque | > 1,5 |

### Fonctionnement courant

- **Synchronisation automatique** chaque jour à 06:30. Les 3 derniers jours sont toujours
  resynchronisés, car Garmin complète parfois ses données après coup.
- **Rattrapage** : au démarrage, si aucune synchronisation n'a réussi depuis plus de 24 h, une
  synchronisation est lancée. Elle rattrape tous les jours manqués.
- **Bouton « Synchroniser maintenant »** : synchronisation immédiate. Si l'import historique est en
  cours, elle s'intercale entre deux jours.
- **Bouton « Reprendre l'import historique »** : relance l'import, par exemple pour retenter les
  appels restés en erreur. Chaque appel est retenté au plus 3 fois.
- **Journal des synchronisations** : date, type, statut, nombre d'appels et détail des erreurs.

### Analyse IA

> **Avertissement** : l'analyse est produite automatiquement par des modèles d'IA à partir de
> statistiques agrégées. Elle ne constitue ni un avis ni un diagnostic médical.

**Configuration** (page *Fournisseurs IA*). Pour chaque fournisseur :

- activation ;
- clé API, rangée dans le Gestionnaire d'identifiants Windows (`RecoverIQ` / `ai:<fournisseur>`) ;
- modèle ;
- adresse de l'API ;
- tarifs.

Le bouton **Tester la connexion** liste les modèles accessibles avec la clé saisie. Ce test ne
consomme aucun jeton.

| Fournisseur | Adresse par défaut | Remarque |
|---|---|---|
| Anthropic | `https://api.anthropic.com` | API Messages |
| OpenAI | `https://api.openai.com/v1` | Chat Completions, sortie JSON forcée |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta` | clé passée en en-tête, jamais dans l'URL |
| Mistral | `https://api.mistral.ai/v1` | format OpenAI |
| Personnalisé | à saisir, par ex. `http://localhost:11434/v1` (Ollama) | tout serveur compatible OpenAI ; clé facultative |

Les **tarifs** sont exprimés en dollars par million de jetons, en entrée et en sortie. Recopiez-les
depuis la page tarifs du fournisseur : ils ne sont pas préremplis, car ils changent souvent. Sans
tarif, les jetons sont comptés mais le coût n'est pas estimé.

**Déroulement d'une analyse** (« Analyser maintenant » sur 7 j, 14 j, 28 j, 90 j ou 1 an, ou rapport
hebdomadaire automatique, par défaut le lundi à 07:30 sur les 7 derniers jours) :

1. **Résumé agrégé** (`ai/summary.py`). Pour chaque indicateur : moyenne, extrêmes, écart type, tendance
   par semaine et écart à une période de référence (4 × la durée analysée, entre 28 et 365 jours).
   S'y ajoutent les totaux de charge et d'activités et, dès 28 jours, les corrélations significatives.
   **Aucune valeur journalière ni aucun identifiant n'est envoyé.** Le résumé exact est archivé et
   consultable sous chaque rapport (« Données envoyées aux modèles »).
2. **Appels en parallèle** aux fournisseurs actifs, chacun avec un délai maximal (120 s par défaut). Un
   fournisseur en échec est signalé : clé refusée, délai dépassé, quota atteint ou réponse hors format.
   Il ne bloque pas les autres.
3. **Format imposé**. Chaque modèle répond en JSON : points clés, tendances, alertes avec sévérité
   (faible, modérée, élevée) et exactement 3 suggestions concrètes. Chaque tendance et chaque alerte
   cite un indicateur du catalogue, ce qui permet de comparer les modèles. La réponse est validée et
   corrigée si possible ; une réponse inexploitable est marquée « format invalide ».
4. **Agrégation** :
   - un seul rapport valide est affiché tel quel ;
   - avec plusieurs rapports, une **comparaison automatique** liste les alertes partagées (consensus),
     les écarts de sévérité, les alertes isolées et les tendances contradictoires ;
   - la **synthèse** est rédigée par l'agrégateur désigné : un fournisseur précis, ou « automatique »,
     c'est-à-dire le premier qui a répondu. Si elle échoue, l'affichage se replie sur la comparaison seule.
5. **Archivage** dans la base, avec la date, la période, les fournisseurs, les modèles, les jetons et le
   coût estimé. Chaque rapport individuel reste consultable.

## Démarrage automatique (optionnel)

La synchronisation quotidienne ne tourne que si l'application est lancée. Pour la démarrer à
l'ouverture de session, en arrière-plan et sans fenêtre :

```powershell
$py = (Resolve-Path .\.venv\Scripts\pythonw.exe).Path
$action = New-ScheduledTaskAction -Execute $py -Argument "-m recoveriq" -WorkingDirectory (Get-Location).Path
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
Register-ScheduledTask -TaskName "RecoverIQ" -Action $action -Trigger $trigger -Description "RecoverIQ - serveur local"
```

Pour la supprimer : `Unregister-ScheduledTask -TaskName RecoverIQ`.

## Sécurité et emplacement des données

| Élément | Emplacement |
|---|---|
| Base SQLite, journaux | `%USERPROFILE%\.recoveriq\` (`recoveriq.db`, `logs\recoveriq.log`) |
| Mot de passe Garmin | Gestionnaire d'identifiants Windows, service `RecoverIQ` |
| Tokens de session Garmin | `%USERPROFILE%\.recoveriq\garmin_tokens.bin`, chiffré par DPAPI (lisible uniquement par votre compte Windows) |
| Clés API des fournisseurs d'IA | Gestionnaire d'identifiants Windows, service `RecoverIQ`, nom `ai:<fournisseur>` ; jamais renvoyées à l'interface |
| Rapports d'analyse IA | Base SQLite (tables `ai_report`, `ai_provider_result`) |

Le bouton **Se déconnecter** supprime le mot de passe et les tokens. Les données importées sont
conservées. Pour tout réinitialiser, supprimez le dossier `%USERPROFILE%\.recoveriq\`.

**Pourquoi pas `AppData` ?** Lorsqu'un processus tourne dans le contexte d'un paquet MSIX (Python
du Microsoft Store, ou serveur lancé depuis une application empaquetée), Windows redirige
silencieusement ses écritures dans `AppData` vers un dossier privé du paquet. Les données
deviennent alors invisibles pour un lancement normal. Le profil utilisateur n'est pas redirigé.

La version 0.1 stockait ses données dans `%LOCALAPPDATA%\RecoverIQ\`. Au premier démarrage de la
version 0.2, la base et les tokens sont copiés automatiquement vers le nouveau dossier. L'ancien
dossier n'est pas modifié : vous pouvez le supprimer après vérification.

## Configuration avancée

Variables d'environnement, toutes optionnelles :

| Variable | Défaut | Rôle |
|---|---|---|
| `RECOVERIQ_HOME` | `%USERPROFILE%\.recoveriq` | Dossier des données |
| `RECOVERIQ_PORT` | `8765` | Port HTTP |
| `RECOVERIQ_DAILY_SYNC_TIME` | `06:30` | Heure de la synchronisation quotidienne |
| `RECOVERIQ_RESYNC_DAYS` | `3` | Jours resynchronisés à chaque passage |
| `RECOVERIQ_REQUEST_PAUSE` | `1.5` | Pause entre deux appels Garmin (s) |
| `RECOVERIQ_HISTORY_START` | *(première activité)* | Date de début forcée de l'historique (`YYYY-MM-DD`). Prise en compte au premier import uniquement. |
| `RECOVERIQ_EMPTY_STREAK_STOP` | `90` | L'import d'un indicateur s'arrête après N jours consécutifs sans donnée, par exemple avant l'achat de la montre |

## Architecture

```
recoveriq/
├── config.py            Paramètres (variables d'environnement)
├── secrets_store.py     Accès keyring (Gestionnaire d'identifiants)
├── metrics.py           Catalogue des indicateurs
├── scheduler.py         APScheduler : synchronisation quotidienne, rapport IA hebdomadaire
├── main.py              Application FastAPI (démarrage / arrêt des services)
├── db/                  schema.sql + migrations (002 IA, 003 relevés Readiness, 004 montres), connexion + migrations, repository, migration 0.1 → 0.2
├── analytics/
│   ├── catalog.py       Séries affichables (ajouter une courbe = une ligne)
│   ├── series.py        Moyennes mobiles, ligne de base, bande de normalité, tendance
│   ├── home.py          Cartes du jour
│   ├── training.py      Charge, zones du ratio A/C, focus, volume hebdomadaire
│   ├── correlations.py  Corrélations et comparaison semaine / week-end
│   └── devices.py       Matériel : montres des activités
├── ai/
│   ├── providers/       Classe de base abstraite + un adaptateur par fournisseur (httpx, sans SDK)
│   ├── summary.py       Résumé agrégé envoyé aux modèles
│   ├── prompts.py       Prompts et avertissement médical
│   ├── report_format.py Format JSON imposé et validation tolérante
│   ├── compare.py       Comparaison déterministe des rapports (consensus, écarts)
│   ├── service.py       Orchestration : appels parallèles, délais, synthèse, coût
│   ├── settings.py      Réglages (base) et clés (trousseau Windows)
│   └── store.py         Archivage des rapports
├── devtools/demo_data.py  Base de démonstration (développement, tests)
├── garmin/
│   ├── auth.py          Connexion, MFA, restauration de session
│   ├── token_store.py   Fichier de tokens chiffré DPAPI
│   ├── client.py        Cadence des appels, reprise sur 429, classement des réponses
│   ├── registry.py      Déclaration des appels Garmin (point d'extension)
│   ├── parsers.py       JSON brut → tables normalisées
│   └── sync.py          Import historique avec reprise + synchronisation incrémentale
├── api/                 Routes REST (JSON + exports CSV)
└── static/              Interface monopage (JS modules, Chart.js 4.4.7 embarqué, sans build)
```

### Appels Garmin utilisés (garminconnect 0.3.2)

| Appel | Portée | Indicateurs alimentés |
|---|---|---|
| `get_user_summary` | jour | Body Battery, stress et répartition, minutes d'intensité, FC repos, SpO2 et respiration de jour |
| `get_hrv_data` | jour | VFC |
| `get_training_status` | jour | Charge aiguë et chronique, ACWR, focus de charge, statut, VO2 max, nom des montres |
| `get_sleep_data` | jour | Sommeil, respiration et SpO2 nocturnes, recharge nocturne de la Body Battery |
| `get_training_readiness` | jour | Readiness (score du matin et dernier score), temps de récupération, relevés horodatés (récupération après chaque activité) |
| `get_body_battery` | plage | Body Battery (charge, décharge, min, max) |
| `get_hill_score` | plage | Hill Score |
| `get_endurance_score` | plage, puis jour | Endurance Score : moyenne hebdomadaire pour l'historique, valeur exacte en synchro quotidienne |
| `get_activities_by_date` | plage | Activités |

**Ajouter un indicateur :**

1. Déclarer un `Fetcher` dans `garmin/registry.py`.
2. Écrire son parser dans `garmin/parsers.py`.
3. Si besoin, ajouter sa table dans `db/schema.sql`, via une migration si la base existe déjà.

### Données brutes et retraitement

Chaque réponse Garmin est conservée telle quelle dans `raw_response`. Si Garmin modifie un nom de
champ, il suffit de corriger le parser et de retraiter les réponses brutes, sans nouvel appel réseau.

Un indicateur que votre montre ne fournit pas apparaît comme « Non fourni par la montre » : il
n'est jamais traité comme une erreur.

### Note sur garth

Depuis la version 0.3, `garminconnect` n'utilise plus `garth` : l'authentification est native.
La sauvegarde et la réutilisation des tokens fonctionnent de la même manière, via le fichier chiffré
décrit plus haut.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Les tests n'appellent jamais Garmin ni aucun fournisseur d'IA. Ils utilisent un faux client Garmin,
des réponses HTTP simulées (`httpx.MockTransport`) et une base de démonstration.

Pour travailler sur l'interface sans toucher à vos données, générez une base de démonstration
(400 jours) et lancez une seconde instance sur un autre port :

```powershell
.\.venv\Scripts\python.exe -m recoveriq.devtools.demo_data data\demo 400
$env:RECOVERIQ_HOME = "data\demo"; $env:RECOVERIQ_PORT = "8766"; .\.venv\Scripts\python.exe -m recoveriq
```

## Licence

MIT, voir le fichier [LICENSE](LICENSE).
