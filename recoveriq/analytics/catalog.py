"""Catalogue des séries affichables : une série = une colonne d'une table journalière.

Ajouter une courbe au tableau de bord = ajouter une entrée ici. ``scale`` convertit
l'unité de stockage vers l'unité d'affichage (ex. secondes → heures).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Series:
    key: str
    table: str
    column: str
    label: str
    unit: str
    group: str
    higher_is_better: bool | None = True   # None = ni bon ni mauvais (ex. charge)
    scale: float = 1.0
    decimals: int = 0

    @property
    def description(self) -> str:
        """Explication de l'indicateur pour l'utilisateur (vide si aucune)."""
        return DESCRIPTIONS.get(self.key, "")


SERIES: tuple[Series, ...] = (
    # Body Battery
    Series("bb_at_wake", "daily_body_battery", "at_wake", "Body Battery au réveil", "", "Body Battery"),
    Series("bb_highest", "daily_body_battery", "highest", "Body Battery max", "", "Body Battery"),
    Series("bb_lowest", "daily_body_battery", "lowest", "Body Battery min", "", "Body Battery"),
    Series("bb_charged", "daily_body_battery", "charged", "Body Battery : recharge", "", "Body Battery"),
    Series("bb_drained", "daily_body_battery", "drained", "Body Battery : décharge", "", "Body Battery", higher_is_better=False),
    Series("bb_sleep_charge", "daily_body_battery", "sleep_charge", "Body Battery : recharge nocturne", "", "Body Battery"),
    # VFC / FC
    Series("hrv", "daily_hrv", "last_night_avg", "VFC nocturne", "ms", "Cœur"),
    Series("hrv_weekly", "daily_hrv", "weekly_avg", "VFC moyenne 7 j (Garmin)", "ms", "Cœur"),
    Series("rhr", "daily_rhr", "resting_hr", "FC au repos", "bpm", "Cœur", higher_is_better=False),
    # Sommeil
    Series("sleep_score", "daily_sleep", "score", "Score de sommeil", "", "Sommeil"),
    Series("sleep_duration", "daily_sleep", "duration_s", "Durée de sommeil", "h", "Sommeil", scale=1 / 3600, decimals=2),
    Series("sleep_deep", "daily_sleep", "deep_s", "Sommeil profond", "h", "Sommeil", scale=1 / 3600, decimals=2),
    Series("sleep_light", "daily_sleep", "light_s", "Sommeil léger", "h", "Sommeil", higher_is_better=None, scale=1 / 3600, decimals=2),
    Series("sleep_rem", "daily_sleep", "rem_s", "Sommeil paradoxal", "h", "Sommeil", scale=1 / 3600, decimals=2),
    Series("sleep_awake", "daily_sleep", "awake_s", "Éveil nocturne", "min", "Sommeil", higher_is_better=False, scale=1 / 60),
    Series("resp_sleep", "daily_respiration", "sleep_avg", "Respiration nocturne", "rpm", "Sommeil", higher_is_better=None, decimals=1),
    Series("spo2_sleep", "daily_spo2", "sleep_avg", "SpO2 nocturne", "%", "Sommeil", decimals=1),
    Series("sleep_hr", "daily_sleep", "avg_hr", "FC moyenne pendant le sommeil", "bpm", "Sommeil", higher_is_better=False),
    Series("sleep_stress", "daily_sleep", "avg_sleep_stress", "Stress pendant le sommeil", "", "Sommeil",
           higher_is_better=False),
    Series("sleep_need", "daily_sleep", "sleep_need_min", "Besoin de sommeil (Garmin)", "h", "Sommeil",
           higher_is_better=None, scale=1 / 60, decimals=2),
    Series("naps", "daily_sleep", "nap_s", "Siestes", "min", "Sommeil", higher_is_better=None, scale=1 / 60),
    # Stress
    Series("stress_avg", "daily_stress", "avg", "Stress moyen", "", "Stress", higher_is_better=False),
    Series("stress_high", "daily_stress", "high_s", "Stress élevé", "min", "Stress", higher_is_better=False, scale=1 / 60),
    Series("stress_rest", "daily_stress", "rest_s", "Repos (stress)", "h", "Stress", scale=1 / 3600, decimals=1),
    # Récupération
    Series("readiness", "daily_readiness", "score", "Training Readiness", "", "Récupération"),
    Series("recovery_time", "daily_readiness", "recovery_time_min", "Temps de récupération", "h", "Récupération",
           higher_is_better=False, scale=1 / 60, decimals=1),
    Series("rf_sleep", "daily_readiness", "sleep_factor_pct", "Readiness : facteur sommeil", "%", "Récupération"),
    Series("rf_recovery", "daily_readiness", "recovery_factor_pct", "Readiness : facteur temps de récupération", "%", "Récupération"),
    Series("rf_acwr", "daily_readiness", "acwr_factor_pct", "Readiness : facteur charge aiguë", "%", "Récupération"),
    Series("rf_hrv", "daily_readiness", "hrv_factor_pct", "Readiness : facteur VFC", "%", "Récupération"),
    Series("rf_stress", "daily_readiness", "stress_history_factor_pct", "Readiness : facteur historique de stress", "%", "Récupération"),
    Series("rf_sleep_history", "daily_readiness", "sleep_history_factor_pct", "Readiness : facteur historique de sommeil", "%", "Récupération"),
    # Entraînement
    Series("intensity", "daily_intensity", "total_min", "Minutes d'intensité", "min", "Entraînement"),
    Series("intensity_moderate", "daily_intensity", "moderate_min", "Minutes d'intensité modérée", "min", "Entraînement"),
    Series("intensity_vigorous", "daily_intensity", "vigorous_min", "Minutes d'intensité vigoureuse", "min", "Entraînement"),
    Series("weekly_load", "daily_training_status", "weekly_load", "Charge sur 7 jours (statut)", "", "Entraînement",
           higher_is_better=None),
    Series("acute_load", "daily_training_load", "acute_load", "Charge aiguë", "", "Entraînement", higher_is_better=None),
    Series("chronic_load", "daily_training_load", "chronic_load", "Charge chronique", "", "Entraînement", higher_is_better=None),
    Series("acwr", "daily_training_load", "acwr", "Ratio aiguë / chronique", "", "Entraînement", higher_is_better=None, decimals=2),
    Series("vo2max", "daily_vo2max", "running", "VO2 max (course)", "ml/kg/min", "Forme", decimals=1),
    Series("vo2max_cycling", "daily_vo2max", "cycling", "VO2 max (vélo)", "ml/kg/min", "Forme", decimals=1),
    Series("fitness_age", "daily_fitness_age", "fitness_age", "Âge de forme physique", "ans", "Forme",
           higher_is_better=False, decimals=1),
    Series("fitness_age_achievable", "daily_fitness_age", "achievable_age", "Âge de forme atteignable", "ans",
           "Forme", higher_is_better=False, decimals=1),
    Series("fitness_trend", "daily_training_status", "fitness_trend", "Tendance de forme", "", "Forme",
           decimals=1),
    Series("endurance", "daily_endurance", "score", "Endurance Score", "", "Forme"),
    Series("hill", "daily_hill", "overall", "Hill Score", "", "Forme"),
    Series("lt_hr", "daily_lactate_threshold", "heart_rate", "Seuil lactique : FC", "bpm", "Forme", higher_is_better=None),
    Series("lt_pace", "daily_lactate_threshold", "pace_s_per_km", "Seuil lactique : allure", "min/km", "Forme",
           higher_is_better=False, scale=1 / 60, decimals=2),
    Series("lt_power", "daily_lactate_threshold", "power", "Seuil lactique : puissance", "W", "Forme"),
)

SERIES_BY_KEY = {s.key: s for s in SERIES}

# Explication affichée avec chaque indicateur : ce qu'il mesure et comment le lire.
DESCRIPTIONS: dict[str, str] = {
    # Body Battery
    "bb_at_wake": "Réserve d'énergie estimée par Garmin (0 à 100) au réveil, calculée à partir de la VFC, "
                  "du stress, du sommeil et de l'activité. C'est le meilleur résumé de la récupération "
                  "nocturne : au-dessus de 75 la nuit a bien rechargé, en dessous de 50 la récupération est incomplète.",
    "bb_highest": "Valeur la plus haute du Body Battery dans la journée, en général atteinte au réveil. "
                  "Elle indique jusqu'où la réserve d'énergie a pu remonter.",
    "bb_lowest": "Valeur la plus basse du Body Battery dans la journée, en général atteinte le soir. "
                 "Un minimum très bas signale une journée qui a beaucoup puisé dans les réserves.",
    "bb_charged": "Points de Body Battery regagnés dans la journée (sommeil, repos, moments calmes). "
                  "Plus le total est élevé, mieux le corps a récupéré.",
    "bb_drained": "Points de Body Battery dépensés dans la journée par l'activité physique, le stress et l'éveil. "
                  "Une forte décharge n'est pas mauvaise en soi (entraînement) mais doit être compensée par la recharge.",
    "bb_sleep_charge": "Points de Body Battery regagnés pendant la nuit. Une recharge nocturne faible "
                       "(sommeil court, alcool, maladie, entraînement tardif) annonce une journée avec moins de réserve.",
    # Cœur
    "hrv": "Variabilité de la fréquence cardiaque : variation de l'intervalle entre deux battements, "
           "moyennée pendant le sommeil (RMSSD, en millisecondes). Une VFC élevée par rapport à votre "
           "propre normale traduit un système nerveux reposé ; une baisse durable signale fatigue, stress, "
           "maladie ou surentraînement. Les valeurs sont très individuelles : comparez-vous à vous-même.",
    "hrv_weekly": "Moyenne de la VFC nocturne sur les 7 derniers jours, calculée par Garmin. "
                  "Elle lisse les variations d'une nuit à l'autre et sert à situer votre statut VFC "
                  "par rapport à votre plage de référence.",
    "rhr": "Fréquence cardiaque la plus basse mesurée au repos sur la journée, en battements par minute. "
           "Elle baisse quand la forme aérobie progresse ; une hausse de quelques battements au-dessus de "
           "la normale peut signaler fatigue, déshydratation, alcool ou début de maladie.",
    # Sommeil
    "sleep_score": "Note Garmin de 0 à 100 qui combine durée, phases de sommeil, éveils et stress nocturne. "
                   "90 et plus : excellent ; 80 à 89 : bon ; 60 à 79 : passable ; moins de 60 : médiocre.",
    "sleep_duration": "Temps total passé à dormir, hors éveils. Pour un adulte, 7 à 9 heures sont recommandées ; "
                      "les sportifs ont souvent besoin du haut de cette plage.",
    "sleep_deep": "Temps passé en sommeil profond (lent), la phase la plus réparatrice physiquement : "
                  "sécrétion d'hormone de croissance, réparation musculaire. Il représente en général 15 à 25 % "
                  "de la nuit et se concentre en début de nuit.",
    "sleep_light": "Temps passé en sommeil léger, la phase la plus longue de la nuit (environ la moitié). "
                   "Elle fait la transition entre les autres phases ; sa durée n'est ni bonne ni mauvaise en soi.",
    "sleep_rem": "Temps passé en sommeil paradoxal (REM), la phase des rêves, importante pour la mémoire, "
                 "l'apprentissage et l'équilibre émotionnel. Il représente en général 20 à 25 % de la nuit "
                 "et se concentre en fin de nuit.",
    "sleep_awake": "Temps passé éveillé entre l'endormissement et le lever. Quelques minutes sont normales ; "
                   "un éveil nocturne prolongé fragmente le sommeil et réduit la récupération.",
    "resp_sleep": "Nombre moyen de respirations par minute pendant le sommeil. Il est stable d'une nuit à l'autre "
                  "chez une même personne (souvent 12 à 20) : un écart net par rapport à votre normale peut "
                  "signaler une maladie, l'altitude ou une forte fatigue.",
    "sleep_hr": "Fréquence cardiaque moyenne pendant la nuit. Elle est en général un peu au-dessus de la FC "
                "au repos ; une nuit nettement plus haute que d'habitude signale une récupération perturbée "
                "(entraînement tardif, alcool, repas lourd, chaleur, début de maladie).",
    "sleep_stress": "Niveau de stress moyen mesuré par Garmin pendant le sommeil (0 à 100). Une nuit réparatrice "
                    "reste très basse, souvent sous 15 ; une valeur élevée indique que le système nerveux "
                    "n'a pas vraiment récupéré.",
    "sleep_need": "Durée de sommeil recommandée par Garmin pour la nuit suivante. Elle part d'une base "
                  "personnelle et s'ajuste selon l'entraînement récent, la VFC, les siestes et la dette de "
                  "sommeil des nuits précédentes.",
    "naps": "Durée totale des siestes détectées par la montre dans la journée.",
    "spo2_sleep": "Saturation en oxygène du sang mesurée au poignet pendant le sommeil. Elle se situe "
                  "habituellement entre 95 et 100 % ; des valeurs plus basses sont normales en altitude. "
                  "La mesure optique est moins précise qu'un oxymètre médical.",
    # Stress
    "stress_avg": "Niveau de stress moyen de la journée (0 à 100), estimé par Garmin à partir de la VFC "
                  "pendant les périodes sans activité. 0 à 25 : repos ; 26 à 50 : faible ; 51 à 75 : moyen ; "
                  "76 à 100 : élevé. Il reflète la charge physiologique, pas seulement psychologique.",
    "stress_high": "Temps passé en stress élevé (niveau 76 à 100) dans la journée. Des durées importantes "
                   "et répétées limitent la recharge du Body Battery.",
    "stress_rest": "Temps passé au repos (stress de 0 à 25), sommeil compris. Plus il est long, plus le corps "
                   "a eu l'occasion de récupérer.",
    # Récupération
    "readiness": "Score Garmin de 0 à 100 qui indique si vous êtes prêt à vous entraîner intensément. "
                 "Il combine sommeil, temps de récupération, VFC, charge aiguë et historique de stress. "
                 "75 et plus : élevé ; 50 à 74 : modéré ; 25 à 49 : faible ; moins de 25 : très faible.",
    "recovery_time": "Temps restant, estimé par Garmin, avant d'être pleinement récupéré pour un nouvel effort "
                     "intense. Il augmente après chaque séance selon sa difficulté et diminue avec le repos "
                     "et le sommeil.",
    "rf_sleep": "Part du score de sommeil de la nuit dans le Training Readiness du matin (0 à 100 %). "
                "100 % : la nuit ne pénalise pas le score ; une valeur basse indique que le sommeil le tire vers le bas.",
    "rf_recovery": "Contribution du temps de récupération restant au Training Readiness (0 à 100 %). "
                   "Elle baisse après une séance difficile et remonte à mesure que la récupération avance.",
    "rf_acwr": "Contribution de la charge aiguë au Training Readiness (0 à 100 %). Elle baisse quand la "
               "charge des 7 derniers jours monte vite par rapport à l'habitude.",
    "rf_hrv": "Contribution de la VFC au Training Readiness (0 à 100 %). Elle est élevée quand la VFC "
              "moyenne sur 7 jours est dans votre plage habituelle ou au-dessus.",
    "rf_stress": "Contribution de l'historique de stress (3 derniers jours) au Training Readiness (0 à 100 %). "
                 "Des journées très stressantes la font baisser.",
    "rf_sleep_history": "Contribution de l'historique de sommeil (3 dernières nuits) au Training Readiness "
                        "(0 à 100 %). Plusieurs nuits courtes de suite la font baisser.",
    # Entraînement
    "intensity_moderate": "Minutes d'activité d'intensité modérée (marche rapide, footing facile) dans la journée.",
    "intensity_vigorous": "Minutes d'activité d'intensité vigoureuse dans la journée. Elles comptent double "
                          "dans le total des minutes d'intensité.",
    "weekly_load": "Charge d'entraînement des 7 derniers jours telle que l'affichait le statut d'entraînement "
                   "Garmin des anciennes montres (par exemple la fenix 5S Plus). Les montres récentes ne la "
                   "fournissent plus : la charge aiguë prend le relais. Elle permet de suivre la charge des "
                   "années où la charge aiguë n'existe pas.",
    "intensity": "Minutes d'activité modérée ou intense de la journée, les minutes intenses comptant double. "
                 "L'OMS recommande au moins 150 minutes par semaine.",
    "acute_load": "Charge d'entraînement des 7 derniers jours : somme pondérée de l'effet des séances "
                  "(consommation d'oxygène post-exercice, EPOC). Elle représente la fatigue récente.",
    "chronic_load": "Charge d'entraînement moyenne sur environ 4 semaines. Elle représente le niveau "
                    "d'entraînement auquel le corps est habitué.",
    "acwr": "Ratio entre charge aiguë (7 jours) et charge chronique (4 semaines). Entre 0,8 et 1,3 la charge "
            "progresse de façon équilibrée ; au-dessus de 1,5 l'augmentation est brutale et le risque de "
            "blessure plus élevé ; sous 0,8 l'entraînement diminue.",
    # Forme
    "vo2max": "Consommation maximale d'oxygène estimée par Garmin lors des courses avec GPS et cardio : "
              "le principal indicateur de capacité aérobie. Elle évolue lentement, sur des semaines.",
    "vo2max_cycling": "Consommation maximale d'oxygène estimée lors des sorties vélo avec capteur de puissance. "
                      "Elle est souvent un peu inférieure à la VO2 max de course.",
    "fitness_age": "Âge correspondant à votre condition physique, calculé par Garmin à partir de la VO2 max, de la FC au repos, de l'IMC et des minutes d'activité vigoureuse des dernières semaines. Plus il est inférieur à votre âge réel, meilleure est votre forme. Les anciennes montres le déduisaient de la seule VO2 max, par années entières (20 ans au minimum).",
    "fitness_age_achievable": "Âge de forme que Garmin estime atteignable en atteignant ses objectifs : jours et minutes d'activité vigoureuse par semaine, IMC.",
    "fitness_trend": "Évolution récente de la VO2 max selon le statut d'entraînement Garmin : +1 en hausse, 0 stable, −1 en baisse. Les moyennes mobiles indiquent la tendance dominante sur la période.",
    "endurance": "Score Garmin d'endurance globale, calculé à partir de la VO2 max et du volume et de "
                 "l'intensité de l'entraînement des dernières semaines, toutes activités confondues. "
                 "Plus il est élevé, mieux vous tenez les efforts longs.",
    "lt_hr": "Fréquence cardiaque au seuil lactique, estimée par Garmin lors des courses (ou d'un test guidé). "
             "Au-delà de ce seuil, le lactate s'accumule plus vite qu'il n'est éliminé et l'effort ne peut "
             "être tenu longtemps. Elle sert à calibrer les zones cardiaques.",
    "lt_pace": "Allure de course au seuil lactique, en minutes par kilomètre : l'allure tenable environ une "
               "heure en compétition. Plus elle est rapide (valeur basse), meilleure est l'endurance de course.",
    "lt_power": "Puissance de course au seuil lactique (FTP de course), en watts, mesurée par la montre. "
                "Elle progresse avec l'endurance et dépend du poids saisi dans Garmin.",
    "hill": "Score Garmin d'aptitude en montée (1 à 100), combinant l'endurance en montée (volume "
            "de dénivelé) et la force en montée (performance sur les pentes raides).",
}

# Périodes du sélecteur (jours ; None = tout l'historique).
PERIODS: dict[str, int | None] = {"30": 30, "90": 90, "365": 365, "all": None}
