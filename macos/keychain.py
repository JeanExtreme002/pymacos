# -*- coding: utf-8 -*-

"""
Store and retrieve passwords in the macOS Keychain.

Items are *generic passwords* identified by a ``service`` and an ``account``,
the same kind of item Keychain Access shows as "application password"::

    macos.keychain.set("my-app", "alice", "s3cret")
    macos.keychain.get("my-app", "alice")     # 's3cret'
    macos.keychain.delete("my-app", "alice")

This talks to the Security framework directly (``SecItem*``) rather than the
``security`` command, whose ``-w <password>`` flag would expose the secret to
every user through the process list.

Items get the keychain's default access control, which trusts the app that
created them: here, the Python interpreter, not the script. Any script or
package that interpreter runs (a virtual environment's ``python`` is the same
interpreter) reads them without a prompt, and another interpreter, or the same
one after an upgrade, makes macOS ask the user first. See the Keychain page of
the documentation, "Who can read the items".
"""

import ctypes
from functools import lru_cache
from typing import Dict, List, Optional

from . import _cf
from ._system import framework
from .errors import KeychainError, PermissionDeniedError

__all__ = ["get", "set", "delete", "accounts"]

errSecSuccess = 0
errSecUserCanceled = -128
errSecAuthFailed = -25293
errSecDuplicateItem = -25299
errSecItemNotFound = -25300
errSecInteractionNotAllowed = -25308
errSecDecode = -26275


@lru_cache(maxsize=None)
def _security() -> ctypes.CDLL:
    sec = framework("Security")

    sec.SecItemCopyMatching.argtypes = (_cf.CFTypeRef, ctypes.POINTER(_cf.CFTypeRef))
    sec.SecItemCopyMatching.restype = ctypes.c_int32
    sec.SecItemAdd.argtypes = (_cf.CFTypeRef, ctypes.POINTER(_cf.CFTypeRef))
    sec.SecItemAdd.restype = ctypes.c_int32
    sec.SecItemUpdate.argtypes = (_cf.CFTypeRef, _cf.CFTypeRef)
    sec.SecItemUpdate.restype = ctypes.c_int32
    sec.SecItemDelete.argtypes = (_cf.CFTypeRef,)
    sec.SecItemDelete.restype = ctypes.c_int32
    sec.SecCopyErrorMessageString.argtypes = (ctypes.c_int32, ctypes.c_void_p)
    sec.SecCopyErrorMessageString.restype = _cf.CFTypeRef
    return sec


def _check(status: int) -> None:
    if status == errSecSuccess:
        return

    with _cf.owned(_security().SecCopyErrorMessageString(status, None)) as ref:
        message = _cf.to_str(ref)

    if status in (errSecUserCanceled, errSecAuthFailed, errSecInteractionNotAllowed):
        # Not a KeychainError (see the docs, "Limitations"), but with the same
        # ``status`` to branch on.
        error = PermissionDeniedError("{} (OSStatus {})".format(message or "Keychain access was denied", status))
        error.status = status  # type: ignore[attr-defined]
        raise error
    raise KeychainError(status, message)


def _check_name(label: str, text: str) -> None:
    """Refuse a service or account name before any ``CFString`` is made of it."""
    if not isinstance(text, str):
        raise TypeError("the keychain {} must be a str, not {}".format(label, type(text).__name__))
    # The file-based keychain stores these attributes as C strings: "svc\0x"
    # would silently address (and overwrite) the "svc" item.
    if "\0" in text:
        raise ValueError("the keychain {} must not contain NUL characters".format(label))
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("the keychain {} must be valid Unicode text (no lone surrogates)".format(label)) from None


def _query(service: str, account: str, extra: Optional[Dict[str, int]] = None) -> int:
    """Build the ``CFDictionary`` identifying one generic-password item."""
    _check_name("service", service)
    _check_name("account", account)

    sec = _security()
    service_ref = _cf.string(service)
    account_ref = _cf.string(account)
    try:
        items = {
            _cf.constant(sec, "kSecClass"): _cf.constant(sec, "kSecClassGenericPassword"),
            _cf.constant(sec, "kSecAttrService"): service_ref,
            _cf.constant(sec, "kSecAttrAccount"): account_ref,
        }
        for key, value in (extra or {}).items():
            items[_cf.constant(sec, key)] = value
        return _cf.dictionary(items)
    finally:
        _cf.release(service_ref)
        _cf.release(account_ref)


def get(service: str, account: str) -> Optional[str]:
    """
    Return the password stored for ``service``/``account``, or ``None`` if there is none.

    Raises :class:`~macos.errors.PermissionDeniedError` if the user denies
    access or the keychain is locked and can't ask (SSH), and
    :class:`~macos.errors.KeychainError` for any other failure.
    """
    sec = _security()
    cf = _cf.lib()
    extra = {
        "kSecReturnData": _cf.constant(cf, "kCFBooleanTrue"),
        "kSecMatchLimit": _cf.constant(sec, "kSecMatchLimitOne"),
    }
    result = _cf.CFTypeRef()
    with _cf.owned(_query(service, account, extra)) as query:
        status = sec.SecItemCopyMatching(query, ctypes.byref(result))

    if status == errSecItemNotFound:
        return None
    _check(status)

    with _cf.owned(result.value) as ref:
        secret = _cf.to_bytes(ref)
    try:
        return secret.decode("utf-8")
    except UnicodeDecodeError:
        # Another app stored binary data under this service/account.
        raise KeychainError(errSecDecode, "the stored password is not UTF-8 text") from None


def set(service: str, account: str, password: str) -> None:
    """
    Store ``password`` for ``service``/``account``, replacing any existing one.

    ``password`` must be a ``str``. Raises like :func:`get`.
    """
    if not isinstance(password, str):
        raise TypeError("the keychain password must be a str, not {}".format(type(password).__name__))
    sec = _security()
    secret = _cf.data(password.encode("utf-8"))
    with _cf.owned(secret):
        with _cf.owned(_query(service, account, {"kSecValueData": secret})) as item:
            status = sec.SecItemAdd(item, None)

        if status == errSecDuplicateItem:
            update = _cf.dictionary({_cf.constant(sec, "kSecValueData"): secret})
            with _cf.owned(_query(service, account)) as query, _cf.owned(update):
                status = sec.SecItemUpdate(query, update)

    _check(status)


def delete(service: str, account: str) -> bool:
    """Delete the item for ``service``/``account``. Return ``False`` if it didn't exist. Raises like :func:`get`."""
    with _cf.owned(_query(service, account)) as query:
        status = _security().SecItemDelete(query)

    if status == errSecItemNotFound:
        return False
    _check(status)
    return True


def accounts(service: str) -> List[str]:
    """
    Return the accounts that have a password stored for ``service``.

    Only the account names are read, never the passwords, so this doesn't
    prompt even for items that other apps created. An item with an empty
    account (or none) is listed as ``""``, which :func:`get` and
    :func:`delete` address. Raises like :func:`get`.
    """
    _check_name("service", service)
    sec = _security()
    cf = _cf.lib()
    true = _cf.constant(cf, "kCFBooleanTrue")
    service_ref = _cf.string(service)
    with _cf.owned(service_ref):
        query = _cf.dictionary(
            {
                _cf.constant(sec, "kSecClass"): _cf.constant(sec, "kSecClassGenericPassword"),
                _cf.constant(sec, "kSecAttrService"): service_ref,
                _cf.constant(sec, "kSecReturnAttributes"): true,
                _cf.constant(sec, "kSecMatchLimit"): _cf.constant(sec, "kSecMatchLimitAll"),
            }
        )
    result = _cf.CFTypeRef()
    with _cf.owned(query):
        status = sec.SecItemCopyMatching(query, ctypes.byref(result))
    if status == errSecItemNotFound:
        return []
    _check(status)

    account_key = _cf.constant(sec, "kSecAttrAccount")
    names = []
    with _cf.owned(result.value) as items:
        for item in _cf.items(items):
            # The file-based keychain leaves an empty account out of the
            # attributes: that item is the one account "" addresses.
            value = cf.CFDictionaryGetValue(item, account_key)
            name = _cf.to_str(value) if value else ""
            if name is not None:
                names.append(name)
    return sorted(names)
