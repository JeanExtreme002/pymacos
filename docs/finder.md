# Finder

{mod}`macos.finder` reveals files, moves them to the Trash, manages their
tags and follows aliases, the same way Finder does.

## Revealing a file

```python
import macos

macos.finder.reveal("report.pdf")   # opens a Finder window with it selected
```

## Moving to the Trash

{func}`~macos.finder.trash` moves a file or folder to the Trash and returns
where it ended up:

```python
macos.finder.trash("old.log")   # PosixPath('/Users/alice/.Trash/old.log')
```

Unlike {func}`os.remove` or {func}`shutil.rmtree`, nothing is deleted: the item
can be restored from the Trash with *Put Back*.

## Tags

```python
macos.finder.tags("report.pdf")                       # []
macos.finder.add_tags("report.pdf", "Work", "Red")    # ['Work', 'Red']
macos.finder.remove_tags("report.pdf", "Red")         # ['Work']
macos.finder.set_tags("report.pdf", ["Done"])         # replace them all
macos.finder.set_tags("report.pdf", [])               # remove them all
```

Tags show up in Finder's sidebar and are searchable in Spotlight. Finder's
default tags are named after colors (`"Red"`, `"Orange"`, `"Yellow"`,
`"Green"`, `"Blue"`, `"Purple"`, `"Gray"`).

The tag functions raise `FileNotFoundError` when the path doesn't exist.

## Aliases

A Finder alias (*File › Make Alias*) points to a file or folder and keeps
finding it after it's moved or renamed. Unlike a symbolic link, Python can't
follow it: `os.path.realpath()` and `Path.resolve()` return the alias itself.
{func}`~macos.finder.resolve_alias` returns the original:

```python
macos.finder.resolve_alias("Projects alias")   # PosixPath('/Users/alice/Documents/Projects')
macos.finder.is_alias("Projects alias")        # True
```

{func}`~macos.finder.resolve_alias` also follows symbolic links, and aliases
of aliases, and returns any other path as it is, so it's safe to call on
every path. It raises `FileNotFoundError` when the original was deleted.

{func}`~macos.finder.make_alias` creates one, next to the original and named
`"<name> alias"` as Finder does, or at the path or in the folder you pass:

```python
macos.finder.make_alias("report.pdf")                 # report.pdf alias
macos.finder.make_alias("report.pdf", "~/Desktop")    # ~/Desktop/report.pdf alias
```

It raises `FileExistsError` when something already has the alias's path.

## Thumbnails

{func}`~macos.finder.thumbnail` returns a preview of a file as PNG bytes, like
the ones Finder shows. Documents, images, videos and PDFs get a preview of their
content (through Quick Look); apps, folders and other files get their icon:

```python
from pathlib import Path

Path("preview.png").write_bytes(macos.finder.thumbnail("report.pdf", size=512))
```

`size` is the largest side, in pixels: 256 by default, up to 4096.

## Watching a folder

{func}`~macos.finder.watch` yields an {class}`~macos.finder.Event` each time
something changes in a folder, as it happens, with no polling:

```python
for event in macos.finder.watch("~/Downloads"):
    if event.kind == "created" and event.path.suffix == ".pdf":
        macos.notify(event.path.name, title="New PDF")
```

`event.kind` is `'created'`, `'modified'`, `'deleted'` or `'renamed'` (the new
name of a moved or renamed item), and `event.is_dir` tells folders apart.
`pattern="*.pdf"` (or a list of patterns) keeps only the files whose name
matches.
Subfolders are watched too, unless `recursive=False`. It goes on until you
`break` out of the loop, or `timeout` seconds pass. To wait for one change,
such as a download finishing:

```python
event = macos.finder.wait_for_change("~/Downloads", timeout=60)
```

It uses FSEvents, like Spotlight and Time Machine. Paths come with symbolic
links resolved (`/private/tmp/...` for `/tmp/...`). No permission is needed,
except that the Desktop, Documents and Downloads folders ask for access the
first time, like any access to them.

## The selection

{func}`~macos.finder.selection` returns what's selected in Finder, and
{func}`~macos.finder.current_folder` the folder its front window shows, for
scripts that act on what you picked:

```python
for path in macos.finder.selection():
    macos.image.convert(path, path.with_suffix(".jpg"))

macos.finder.current_folder()   # PosixPath('/Users/alice/Downloads')
```

They ask Finder through AppleScript, so the first time macOS asks to allow it
([Automation](permissions.md#automation)).

## Zip archives

{func}`~macos.finder.compress` zips a file or folder, like Finder's *Compress*,
and {func}`~macos.finder.extract` unzips an archive:

```python
archive = macos.finder.compress("Project")        # Project.zip, next to it
macos.finder.extract(archive, "~/Desktop/copy")
```

Unlike plain zip tools, they keep what macOS stores with files: tags, extended
attributes and permissions.

## Quick Look

{func}`~macos.finder.quick_look` shows a file in Quick Look, the preview Space
opens, and returns at once:

```python
macos.finder.quick_look("report.pdf")
```

## Custom icons

{func}`~macos.finder.set_icon` gives a folder, a file or an app a custom icon,
like pasting one in Get Info:

```python
macos.finder.set_icon("~/Projects", "logo.png")                        # an image
macos.finder.set_icon("~/Projects/app", "/Applications/Xcode.app")     # another item's icon
macos.finder.has_custom_icon("~/Projects")                             # True
macos.finder.remove_icon("~/Projects")                                 # its usual icon again
```

Finder and the Dock may take a moment to show it. An app in `/Applications`
may need an administrator's rights. {func}`~macos.finder.has_custom_icon` asks
a symbolic link about itself, not about what it points to.

## The largest files

{func}`~macos.finder.largest` finds what takes the most room in a folder and
its subfolders, quickly, through Spotlight's index:

```python
for path, size in macos.finder.largest("~", count=10):
    print("{:>8.1f} MB  {}".format(size / 1e6, path))
```

Files under `at_least` bytes (1 MB) are left out. Folders Spotlight doesn't
index, hidden ones and `~/Library`, are walked instead, which is slower, when
they're the folder or right under it; hidden folders deeper in (a project's
`.git`) aren't searched. When Spotlight finds nothing there (it's off, or
hasn't indexed that disk), the whole folder is walked file by file.

Walking a big folder, a whole disk or a network share, can take very long:
after `timeout` seconds of it (60 by default) {func}`~macos.finder.largest`
raises `TimeoutError` rather than return an answer missing files. Pass
`timeout=None` to walk for as long as it takes.

## Finder settings

The settings people change most, each with its reader: they apply at once, as
Finder is relaunched ({func}`~macos.finder.restart` relaunches it yourself).

| Read | Change | Shows |
|---|---|---|
| {func}`~macos.finder.show_hidden_files` | {func}`~macos.finder.set_show_hidden_files` | hidden files, such as `.git` (⌘⇧. toggles it too) |
| {func}`~macos.finder.show_extensions` | {func}`~macos.finder.set_show_extensions` | every file name's extension |
| {func}`~macos.finder.show_path_bar` | {func}`~macos.finder.set_show_path_bar` | the folders leading to the one shown |
| {func}`~macos.finder.show_status_bar` | {func}`~macos.finder.set_show_status_bar` | the item count and the free space |
| {func}`~macos.finder.show_full_path_in_title` | {func}`~macos.finder.set_show_full_path_in_title` | the whole path in the window's title |
| {func}`~macos.finder.show_desktop_icons` | {func}`~macos.finder.set_show_desktop_icons` | the files on the desktop; `False` hides them for a clean screen |
| {func}`~macos.finder.folders_first` | {func}`~macos.finder.set_folders_first` | folders before files when sorting by name |
| {func}`~macos.finder.extension_change_warning` | {func}`~macos.finder.set_extension_change_warning` | a warning before a file's extension changes |
| {func}`~macos.finder.remove_old_trash_items` | {func}`~macos.finder.set_remove_old_trash_items` | items deleted from the Trash after 30 days |
| {func}`~macos.finder.quit_menu` | {func}`~macos.finder.set_quit_menu` | Quit Finder (⌘Q) in its menu |
| {func}`~macos.finder.show_library_folder` | {func}`~macos.finder.set_show_library_folder` | the `~/Library` folder in your home |

```python
macos.finder.set_show_hidden_files(True)
macos.finder.set_show_extensions(True)
```

And how new windows and searches behave:

| Read | Change | Values |
|---|---|---|
| {func}`~macos.finder.default_view` | {func}`~macos.finder.set_default_view` | `"icons"`, `"list"`, `"columns"` or `"gallery"`, for folders not yet opened |
| {func}`~macos.finder.new_window_folder` | {func}`~macos.finder.set_new_window_folder` | the folder a new window opens on |
| {func}`~macos.finder.search_scope` | {func}`~macos.finder.set_search_scope` | `"this_mac"`, `"current_folder"` or `"previous"` |

```python
macos.finder.set_default_view("columns")
macos.finder.set_new_window_folder("~/Projects")
macos.finder.set_search_scope("current_folder")
```

{func}`~macos.finder.set_show_drives_on_desktop` chooses which disks show on
the desktop: the Mac's own (`internal`), USB and Thunderbolt ones
(`external`), CDs and the like (`removable`) and network shares (`servers`):

```python
macos.finder.set_show_drives_on_desktop(external=False, servers=True)
macos.finder.drives_on_desktop()   # {'internal': False, 'external': False, 'removable': True, 'servers': True}
```

{func}`~macos.finder.set_desktop_view` changes how the desktop shows its icons,
as its View › Show View Options does; the options left out stay as they
are:

```python
macos.finder.set_desktop_view(icon_size=48, grid_spacing=30, sort="kind")
macos.finder.desktop_view()   # {'icon_size': 48, 'grid_spacing': 30, 'sort': 'kind', ...}
```

`icon_size` is from 16 to 128 points, `grid_spacing` from 1 to 100, and
`text_size`, the size of the names, from 10 to 16. `sort` keeps the icons in
order (`"snap_to_grid"`, `"name"`, `"kind"`, `"date_added"`,
`"date_modified"`, `"size"`, `"tags"`...), or `None` lets them be placed
freely. `show_item_info=True` adds a line under each name (a disk's free
space, a folder's item count), and `labels_on_bottom=False` puts the names to
the right of the icons.

## Reference

- {func}`macos.finder.reveal`
- {func}`macos.finder.trash`
- {func}`macos.finder.tags`
- {func}`macos.finder.set_tags`
- {func}`macos.finder.add_tags`
- {func}`macos.finder.remove_tags`
- {func}`macos.finder.thumbnail`
- {func}`macos.finder.is_alias`
- {func}`macos.finder.resolve_alias`
- {func}`macos.finder.make_alias`
- {func}`macos.finder.watch`
- {func}`macos.finder.wait_for_change`
- {class}`macos.finder.Event`
- {func}`macos.finder.selection`
- {func}`macos.finder.current_folder`
- {func}`macos.finder.compress`
- {func}`macos.finder.extract`
- {func}`macos.finder.quick_look`
- {func}`macos.finder.show_hidden_files`
- {func}`macos.finder.set_show_hidden_files`
- {func}`macos.finder.show_extensions`
- {func}`macos.finder.set_show_extensions`
- {func}`macos.finder.show_path_bar`
- {func}`macos.finder.set_show_path_bar`
- {func}`macos.finder.show_status_bar`
- {func}`macos.finder.set_show_status_bar`
- {func}`macos.finder.show_desktop_icons`
- {func}`macos.finder.set_show_desktop_icons`
- {func}`macos.finder.default_view`
- {func}`macos.finder.set_default_view`
- {func}`macos.finder.show_library_folder`
- {func}`macos.finder.set_show_library_folder`
- {func}`macos.finder.new_window_folder`
- {func}`macos.finder.set_new_window_folder`
- {func}`macos.finder.search_scope`
- {func}`macos.finder.set_search_scope`
- {func}`macos.finder.show_full_path_in_title`
- {func}`macos.finder.set_show_full_path_in_title`
- {func}`macos.finder.folders_first`
- {func}`macos.finder.set_folders_first`
- {func}`macos.finder.extension_change_warning`
- {func}`macos.finder.set_extension_change_warning`
- {func}`macos.finder.remove_old_trash_items`
- {func}`macos.finder.set_remove_old_trash_items`
- {func}`macos.finder.drives_on_desktop`
- {func}`macos.finder.set_show_drives_on_desktop`
- {func}`macos.finder.restart`
- {func}`macos.finder.quit_menu`
- {func}`macos.finder.set_quit_menu`
- {func}`macos.finder.desktop_view`
- {func}`macos.finder.set_desktop_view`
- {func}`macos.finder.set_icon`
- {func}`macos.finder.remove_icon`
- {func}`macos.finder.has_custom_icon`

- {func}`macos.finder.largest`
