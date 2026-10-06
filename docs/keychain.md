# Keychain

{mod}`macos.keychain` stores passwords in the macOS Keychain, encrypted and
tied to the user's login.

```python
import macos

macos.keychain.set("my-app", "alice", "s3cret")
macos.keychain.get("my-app", "alice")      # 's3cret'
macos.keychain.delete("my-app", "alice")   # True
macos.keychain.get("my-app", "alice")      # None
```

Each item is identified by a **service** (usually your app's name) and an **account** (usually a user name).

{func}`~macos.keychain.set` replaces the
password if the item already exists. {func}`~macos.keychain.delete` returns
`False` if there was nothing to delete.

## Listing accounts

{func}`~macos.keychain.accounts` returns the accounts that have a password for
a service. It reads only the names, never the passwords:

```python
macos.keychain.accounts("my-app")   # ['alice', 'bob']
```

## Keeping secrets out of your code

Store an API token once:

```python
macos.keychain.set("openai", "default", "sk-...")
```

Then read it wherever you need it, instead of keeping it in a `.env` file or in
the source code:

```python
api_key = macos.keychain.get("openai", "default")
```

## Seeing the items in Keychain Access

The items are *generic passwords* in the **login** keychain:

1. Open **Keychain Access** (search for it with Spotlight).
2. Select the **login** keychain and the **Passwords** tab.
3. Search for your service name. The item's *Name* is the service and its
   *Account* is the account.

The **Passwords** app in recent macOS versions doesn't list these items; use
Keychain Access. From the terminal:

```bash
security find-generic-password -s my-app -a alice -w
```

## Security

The password goes straight to the Security framework. It is never passed on a
command line, where every user on the Mac could see it in the process list.

### Who can read the items

The items get the keychain's default access control: the app that created
them is trusted to read them without asking, and any other app makes macOS
ask the user first. Here *the app* is the **Python interpreter** running the
script, not the script. So:

- Any script, package or REPL run by that same interpreter (including a
  virtual environment built on it, whose `python` is a link to it) reads the
  items **without a prompt**. A dependency you install can read every item
  your scripts stored; a Keychain item is no more private, from other Python
  code run by the same interpreter, than a file in your home folder.
- Another interpreter (another version, Homebrew's instead of python.org's)
  makes macOS ask, and so does the same one after an **upgrade**: a new build
  is a different app to the keychain. Click *Always Allow* to trust it again.
- Other users can't read them: the login keychain is theirs alone, and it's
  locked while they're logged out.

For a secret only one tool should see, keep it out of an interpreter shared
with untrusted code (a dedicated virtual environment doesn't help: it's the
same interpreter), or protect it with something the keychain can't hand
over silently, such as a passphrase the user types. {mod}`macos.auth` adds a
Touch ID prompt in your script, but that's a check within the process, not
access control on the item.

## Limitations

- Service and account names can't contain NUL characters (`"\0"`): the keychain
  would silently cut them there and address a different item, so `pymacos`
  raises `ValueError`.
- If the stored data isn't UTF-8 text (e.g. binary data written by another
  app), {func}`~macos.keychain.get` raises {class}`~macos.KeychainError`.

## Reference

- {func}`macos.keychain.set`
- {func}`macos.keychain.get`
- {func}`macos.keychain.delete`
- {func}`macos.keychain.accounts`
