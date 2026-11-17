"""Analyse IA : résumé agrégé → plusieurs LLM en parallèle → synthèse et archivage.

Principe de confidentialité : seul un **résumé statistique agrégé** (moyennes,
tendances, écarts à la ligne de base) quitte la machine, jamais les mesures
journalières brutes ni les réponses Garmin. Voir :mod:`recoveriq.ai.summary`.
"""
