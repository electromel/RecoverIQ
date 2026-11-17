"""Stockage chiffré des tokens de session Garmin.

Sous Windows, le fichier est chiffré avec DPAPI (``CryptProtectData``) : seul le
compte Windows courant peut le déchiffrer. Les tokens ne passent pas par keyring
car un jeton JWT peut dépasser la taille maximale d'un secret du Gestionnaire
d'identifiants (~2,5 Ko).

Hors Windows (tests, développement), repli sur un fichier non chiffré en lecture
seule pour l'utilisateur, avec avertissement.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

_ENTROPY = b"RecoverIQ-garmin-tokens-v1"
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


if sys.platform == "win32":
    from ctypes import wintypes

    class _DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32

    def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
        buf = ctypes.create_string_buffer(data, len(data))
        return _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    def _dpapi(data: bytes, protect: bool) -> bytes:
        data_in, _keep1 = _blob(data)
        entropy, _keep2 = _blob(_ENTROPY)
        data_out = _DataBlob()
        func = _crypt32.CryptProtectData if protect else _crypt32.CryptUnprotectData
        ok = func(
            ctypes.byref(data_in), None, ctypes.byref(entropy), None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(data_out),
        )
        if not ok:
            raise OSError(f"DPAPI a échoué (code {ctypes.GetLastError()})")
        try:
            return ctypes.string_at(data_out.pbData, data_out.cbData)
        finally:
            _kernel32.LocalFree(data_out.pbData)

    def _encrypt(data: bytes) -> bytes:
        return _dpapi(data, protect=True)

    def _decrypt(data: bytes) -> bytes:
        return _dpapi(data, protect=False)

else:  # pragma: no cover - chemin non Windows
    def _encrypt(data: bytes) -> bytes:
        log.warning("DPAPI indisponible hors Windows : tokens stockés sans chiffrement")
        return data

    def _decrypt(data: bytes) -> bytes:
        return data


class TokenStore:
    """Lecture / écriture du fichier de tokens chiffré."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, tokens: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(_encrypt(tokens.encode("utf-8")))
        os.replace(tmp, self.path)  # remplacement atomique
        if sys.platform != "win32":
            os.chmod(self.path, 0o600)

    def load(self) -> str | None:
        if not self.path.exists():
            return None
        try:
            return _decrypt(self.path.read_bytes()).decode("utf-8")
        except Exception:
            log.exception("Fichier de tokens illisible, il sera ignoré")
            return None

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)
