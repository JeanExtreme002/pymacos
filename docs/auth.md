# Authentication

{mod}`macos.auth` asks the user to confirm it's them, with Touch ID, their
login password or their Apple Watch, before a script does something sensitive.

```python
import macos

if macos.auth.confirm("unlock the production credentials"):
    token = macos.keychain.get("deploy", "prod")
    deploy(token)
```

macOS shows its own prompt, *"Python wants to unlock the production
credentials"*, and checks the fingerprint or the password itself: the script
never sees them, it only learns whether the user confirmed.

## Confirming

{func}`~macos.auth.confirm` returns `True` when the user confirms, and `False`
when they cancel, fail, or don't answer within `timeout` seconds (2 minutes by
default). `reason` completes the prompt's sentence, so write it as what the
script is about to do.

By default the user may type their login password instead of using Touch ID,
so it works on any Mac, and with the lid closed. `only_touch_id=True` accepts
only the fingerprint:

```python
macos.auth.confirm("delete the old backups", only_touch_id=True)
```

When Touch ID isn't set up, or is locked after failed tries, that raises
{class}`~macos.NotSupportedError` instead of asking.

{func}`~macos.auth.is_available` tells, without asking, whether it can:

```python
macos.auth.is_available(only_touch_id=True)   # False on a Mac without Touch ID
```

## Protecting a function

The {func}`~macos.auth.required` decorator asks each time the function is
called, before it runs. When the user doesn't confirm, the call raises
{class}`~macos.PermissionDeniedError` and the function doesn't run:

```python
@macos.auth.required("deploy to production")
def deploy():
    ...

deploy()   # asks first: Touch ID, the password or the Apple Watch
```

## What it protects

It's a check before an action, like `sudo` asking for a password: it stops
someone else using the Mac from running the script's sensitive part. It isn't
encryption: a Keychain item isn't locked behind Touch ID, since that takes an
app signed with Apple's entitlements, which Python isn't.

It checks that the user is present, within this process; it isn't a security
boundary against code running in the same process. Anything that can run
code there (an imported package, a plugin) can skip the prompt: call
whatever the decorated function calls, or reach the original through its
closure. {func}`~macos.auth.required` keeps the function's name and docstring
but drops `__wrapped__`, so `inspect.unwrap()` and tools that follow it don't
skip the prompt by accident, but that's no protection against code meaning
to. Guard what matters with something outside the process too (the
Keychain's own prompt, a server-side check).

Only one prompt shows at a time: calls to {func}`~macos.auth.confirm` from
several threads wait their turn.

## Reference

- {func}`macos.auth.confirm`
- {func}`macos.auth.is_available`
- {func}`macos.auth.required`
