# Browser

{mod}`macos.browser` reads and controls the tabs of Safari, Chrome and the
other Chromium browsers (Brave, Edge, Vivaldi, Chromium).

```python
import macos

macos.browser.current_tab()
# Tab(title='pymacos', url='https://github.com/JeanExtreme002/pymacos', app='Safari', ...)

[tab.url for tab in macos.browser.tabs()]
macos.browser.open("https://macos.readthedocs.io")
```

The first time, macOS asks whether the app running Python may control the
browser ([Automation](permissions.md#automation)). Firefox, Arc, Opera and
a few others can't be scripted this way: naming one with `app=` raises
{class}`~macos.NotSupportedError`, and by default they're passed over.

## Tabs

{func}`~macos.browser.tabs` returns every tab of every window, front window
first, and {func}`~macos.browser.current_tab` the one shown in the front
window. Each {class}`~macos.browser.Tab` has its `title`, `url`, `app`, its
`window` and position (`index`), and whether it's the `active` tab of its
window:

```python
for tab in macos.browser.tabs():
    if "youtube.com" in tab.url:
        tab.close()

docs = next(tab for tab in macos.browser.tabs() if "readthedocs" in tab.url)
docs.activate()   # shows that tab, and brings its window and the browser to the front
docs.reload()

# another page, in the same tab
docs.go("https://macos.readthedocs.io/en/latest/browser.html")
```

A tab is read once: after tabs close or move, read them again.

## Which browser

By default these talk to the browser in front, or else the first one running,
and they never open a browser: with none running, `tabs()` is empty and
`current_tab()` is `None`. `app=` picks one of
{data}`~macos.browser.BROWSERS`:

```python
macos.browser.current_tab(app="Google Chrome")
macos.browser.open("https://example.com", app="Safari")
```

{func}`~macos.browser.open` opens the URL in a new tab, in the default browser
when none is running. A URL starting with `-` raises `ValueError`: the `open`
command would take it as one of its options.

## Running JavaScript

{func}`~macos.browser.run_js` runs JavaScript in the current tab and returns
its result as text (`None` for `undefined`). With no browser running, it raises
{class}`~macos.MacOSError`:

```python
macos.browser.run_js("document.title")

js_code = "JSON.stringify([...document.links].map(a => a.href))"
links = json.loads(macos.browser.run_js(js_code))
```

The browser must allow it, once:

- Safari: *Develop › Allow JavaScript from Apple Events* (to show the Develop
  menu, turn on *Show features for web developers* in Settings › Advanced).
- Chrome and the others: *View › Developer › Allow JavaScript from Apple Events*.

Otherwise it raises {class}`~macos.PermissionDeniedError`, saying where.

The script reaches `osascript` on its standard input, not as an argument, so
a token or password in it doesn't show in the process list (`ps`).

## Reference

- {func}`macos.browser.tabs`
- {func}`macos.browser.current_tab`
- {func}`macos.browser.open`
- {func}`macos.browser.run_js`
- {class}`macos.browser.Tab`
- {data}`macos.browser.BROWSERS`
