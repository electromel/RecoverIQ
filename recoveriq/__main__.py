"""``python -m recoveriq`` : démarre le serveur local."""

import sys

import uvicorn

from recoveriq.config import is_packaged_process, is_under_appdata, settings


def main() -> None:
    if is_packaged_process() and is_under_appdata(settings.home):
        sys.exit(
            f"RecoverIQ : le dossier de données {settings.home} est dans AppData et ce processus "
            "s'exécute dans un paquet MSIX : Windows redirigerait les écritures vers un dossier privé.\n"
            "Choisissez un dossier hors d'AppData (RECOVERIQ_HOME) ou lancez run.bat depuis l'Explorateur."
        )
    # Écoute uniquement sur la boucle locale : l'application n'est pas exposée au réseau.
    uvicorn.run("recoveriq.main:app", host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
