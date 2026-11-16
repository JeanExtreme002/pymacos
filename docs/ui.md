# UI Elements

{mod}`macos.ui` reads what an app shows (its buttons, text fields, links,
checkboxes, menus) and uses them: presses a button, fills a field, chooses a
menu item. It reads the Accessibility tree that VoiceOver reads, so it needs
no screenshot, and it works on an app's own controls rather than on
coordinates that change when the window moves.

```python
import macos

for element in macos.ui.elements("Calculator"):
    print(element.role, element.name, element.frame)   # AXButton 7 (316, 618, 40, 40)

for key in ("7", "Multiply", "6", "Equals"):
    macos.ui.find("Calculator", name=key, role="button")[0].press()
```

It needs the [Accessibility permission](permissions.md#accessibility), the same
one {mod}`macos.windows` needs.

## Reading an app

{func}`~macos.ui.elements` returns what an app shows on screen, top to bottom:
the app in front by default, or one given by name, bundle identifier, path or
as an {class}`~macos.apps.App`. Only what can be seen is listed: what's scrolled
out of view, behind another window, or in a minimized one is left out. The
window in front is read, with the panels that float over it (Fonts, an
inspector). When a menu, a modal dialog or a sheet (a save panel) is open, only
it is, since nothing else can be used until it closes.

By default only controls are listed, what's there to be used; `controls_only=False`
adds what's there to be read, such as text, headings, and images with a description:

```python
macos.ui.elements()                                  # the controls of the app in front
macos.ui.elements("Safari", controls_only=False)     # and the text of the page
```

Web pages are read too, in Safari, Chrome and Electron apps. In a page, the
controls are told by their role (a button, a link, a checkbox), as the page's
HTML and ARIA set it. A page of thousands of elements is cut after a few
thousand, or 15 seconds.

{func}`~macos.ui.find` keeps the elements whose name contains `name` (ignoring
case), of `role`. A role is macOS's (`"AXButton"`), said plainly (`"button"`,
`"text field"`, `"pop up button"`), a subrole (`"search field"`), or as the
user's language says it:

```python
macos.ui.find("Mail", name="Send", role="button")
macos.ui.find(role="text field")          # in the app in front
```

{func}`~macos.ui.wait_for` waits until such an element shows up, and returns
it, or `None` after `timeout` seconds. {func}`~macos.ui.focused` returns the
element keystrokes go to, and {func}`~macos.ui.at` the one at a point of the
screen, in whichever app.

## Elements

An {class}`~macos.ui.Element`'s fields are as they were when it was found:

| Field | What it is |
|---|---|
| `role`, `subrole` | what it is, as macOS names it: `'AXButton'`, `'AXSearchField'`... |
| `role_description` | the same, in the user's language: `'button'`, `'text field'` |
| `name` | what a person would call it: its title, the label next to it, its description |
| `value` | what it holds: a field's text, a slider's position, a checkbox's state |
| `checked` | for a checkbox, a radio button or a switch, whether it's on |
| `frame`, `center` | where it is, in points from the top-left of the main display |
| `enabled`, `focused`, `selected` | whether it can be used, has the keyboard, is chosen |
| `actions` | what it can be asked to do: `'AXPress'`, `'AXShowMenu'`... |

Find it again to see a change. Its methods act on it now:

```python
button.press()                     # as a click would, through Accessibility
field.set_value("hello")           # replaces a field's text
field.focus()                      # the app comes to the front, and keystrokes go to it
popup.perform("AXShowMenu")        # any of its actions
row.click(count=2)                 # with the mouse, in its middle
print(window_content.text())       # all the text it holds, scrolled out of view included
```

{meth}`~macos.ui.Element.press` doesn't move the pointer, and works on a window
behind others; an element that can't be pressed that way (a row) is clicked in
its middle instead. Some web forms don't notice a value set with
{meth}`~macos.ui.Element.set_value`: focus the field and type instead, with
{func}`macos.keyboard.type`.

## Menus

{func}`~macos.ui.menu_items` lists every item of an app's menus, the Apple menu
included, with its keyboard shortcut as {func}`macos.keyboard.press` takes it,
and {func}`~macos.ui.click_menu_item` chooses one:

```python
for item in macos.ui.menu_items("Preview"):
    print(" > ".join(item.path), item.shortcut or "")   # File > Export as PDF…

macos.ui.click_menu_item("View > Show Sidebar", app="Finder")
macos.ui.click_menu_item(["Format", "Font", "Bold"], app="TextEdit")
```

A path names the menu, then the item, through any submenus; `"..."` stands for
`"…"`, and case is ignored. An item that isn't there raises `LookupError`,
naming those that are. The app comes to the front first, since its menus act
on its window in front. An app that fills a menu only as it opens (a list of
recent files) shows that menu empty.
