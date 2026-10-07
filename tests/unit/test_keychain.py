"""Unit tests for :mod:`macos.keychain`. They run on any platform."""

import ctypes
import sys
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

import macos
from macos import keychain
from macos.errors import KeychainError, PermissionDeniedError


# Outside macOS the platform guard (NotSupportedError) rightly fires first.
@pytest.mark.skipif(sys.platform != "darwin", reason="loads the Security framework")
@pytest.mark.parametrize("service, account", [("svc\0x", "alice"), ("svc", "al\0ice")])
def test_keychain_rejects_nul_characters(service, account):
    with pytest.raises(ValueError, match="NUL"):
        macos.keychain.get(service, account)


class _FakeSecurity:
    """The ``SecItem*`` functions, answering with the statuses and secret a test sets."""

    def __init__(self, status=0, secret=b"", update_status=0, message="The specified item could not be found."):
        self.status = status
        self.secret = secret
        self.update_status = update_status
        self.message = message
        self.calls = []

    def SecItemCopyMatching(self, query, result):
        self.calls.append("copy")
        if self.status == 0:
            result._obj.value = 42  # the item's data
        return self.status

    def SecItemAdd(self, item, result):
        self.calls.append("add")
        return self.status

    def SecItemUpdate(self, query, update):
        self.calls.append("update")
        return self.update_status

    def SecItemDelete(self, query):
        self.calls.append("delete")
        return self.status

    def SecCopyErrorMessageString(self, status, reserved):
        return 7 if self.message else None


@pytest.fixture
def security(monkeypatch):
    """Replace the Security framework and the CoreFoundation helpers with fakes."""
    fake = _FakeSecurity()

    @contextmanager
    def owned(ref):
        yield ref

    cf = SimpleNamespace(
        CFTypeRef=ctypes.c_void_p,
        lib=lambda: SimpleNamespace(CFDictionaryGetValue=lambda item, key: item),
        constant=lambda library, name: 1,
        owned=owned,
        release=lambda ref: None,
        string=lambda text: 2,
        data=lambda payload: 3,
        dictionary=lambda items: 4,
        to_bytes=lambda ref: fake.secret,
        to_str=lambda ref: fake.message if ref == 7 else ref,
        items=lambda ref: ["bob", None, "alice"],
    )
    monkeypatch.setattr(keychain, "_security", lambda: fake)
    monkeypatch.setattr(keychain, "_cf", cf)
    return fake


def test_success_raises_nothing(security):
    keychain._check(keychain.errSecSuccess)


@pytest.mark.parametrize("status", [keychain.errSecUserCanceled, keychain.errSecAuthFailed, keychain.errSecInteractionNotAllowed])
def test_refusals_raise_permission_denied(security, status):
    with pytest.raises(PermissionDeniedError, match=r"OSStatus {}".format(status)):
        keychain._check(status)


def test_other_statuses_raise_keychain_error_with_the_status(security):
    with pytest.raises(KeychainError) as caught:
        keychain._check(-25291)
    assert caught.value.status == -25291
    assert caught.value.message == security.message


def test_a_status_without_a_message_still_explains_itself(security):
    security.message = None
    with pytest.raises(KeychainError, match=r"Keychain error \(OSStatus -1\)"):
        keychain._check(-1)


def test_get_returns_none_when_there_is_no_item(security):
    security.status = keychain.errSecItemNotFound
    assert keychain.get("svc", "alice") is None


def test_get_decodes_the_secret(security):
    security.secret = "sênha".encode("utf-8")
    assert keychain.get("svc", "alice") == "sênha"


def test_get_refuses_a_secret_that_is_not_text(security):
    security.secret = b"\xff\xfe"
    with pytest.raises(KeychainError) as caught:
        keychain.get("svc", "alice")
    assert caught.value.status == keychain.errSecDecode


def test_set_adds_a_new_item(security):
    keychain.set("svc", "alice", "s3cret")
    assert security.calls == ["add"]


def test_set_updates_an_existing_item(security):
    security.status = keychain.errSecDuplicateItem
    keychain.set("svc", "alice", "s3cret")
    assert security.calls == ["add", "update"]


def test_set_reports_a_failed_update(security):
    security.status = keychain.errSecDuplicateItem
    security.update_status = keychain.errSecAuthFailed
    with pytest.raises(PermissionDeniedError):
        keychain.set("svc", "alice", "s3cret")


def test_delete_says_whether_there_was_an_item(security):
    assert keychain.delete("svc", "alice") is True
    security.status = keychain.errSecItemNotFound
    assert keychain.delete("svc", "alice") is False


def test_accounts_are_sorted_and_skip_unnamed_items(security):
    assert keychain.accounts("svc") == ["alice", "bob"]


def test_accounts_of_an_unknown_service_is_empty(security):
    security.status = keychain.errSecItemNotFound
    assert keychain.accounts("svc") == []


def test_accounts_rejects_nul_characters(security):
    with pytest.raises(ValueError, match="NUL"):
        keychain.accounts("svc\0x")
