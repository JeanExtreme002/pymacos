# Security Policy

## Supported Versions

Security fixes go into the latest release on PyPI. Please upgrade
(`pip install --upgrade pymacos`) before reporting, to check the issue still
exists.

## Reporting a Vulnerability

**Please do not open a public issue for a suspected vulnerability.** Use one
of the channels below instead, so the impact can be assessed and a fix
prepared before the details become public.

- **Preferred:** open a [private security advisory] on GitHub. This creates a
  private thread visible only to the maintainers and the reporter, supports
  CVE assignment, and lets us agree on a disclosure timeline.
- **Alternative:** email `contact@jeanloui.dev` with the subject
  `[pymacos security]`.

When reporting, please include:

- The pymacos version (`macos.__version__`), macOS version, Mac (Apple
  Silicon or Intel) and Python version.
- A minimal script that reproduces the issue.
- The impact you observed and any prerequisites.

## Scope

pymacos wraps macOS services: it talks to system frameworks through `ctypes`
(AppKit, Foundation, Security, IOKit, CoreGraphics) and runs a few system
commands (`osascript`, `say`, `screencapture`, `shortcuts`, `open`).

In scope:

- **Injection:** text passed to pymacos (a notification message, a shortcut
  name, a file path...) being interpreted as shell or AppleScript code, or as
  command-line options.
- **Secret exposure:** a Keychain password becoming visible to other users or
  processes, for example on a command line, in the process list, in logs or in
  exception messages.
- **Temporary files:** files created by pymacos (e.g. the text input of
  `shortcuts.run`) being readable by other users, or left behind.
- **Memory safety:** crashes, memory corruption or undefined behavior caused by
  the library itself, such as a `ctypes` or Objective-C signature mismatch or a
  missing release.
- **Wrong target:** an operation acting on a different item than requested,
  such as the Keychain item, the app process or the file, or running another
  program than the system command it means (one found along `PATH`).

Out of scope:

- macOS privacy prompts and permissions (Screen Recording, Notifications,
  Keychain access). These are documented requirements, not defects.
- Vulnerabilities in macOS itself or in the system commands pymacos runs.
  Please report those to Apple.
- Using pymacos on a Mac or data you are not authorized to access.

[private security advisory]: https://github.com/JeanExtreme002/pymacos/security/advisories/new
