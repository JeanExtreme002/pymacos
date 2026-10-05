# Camera

{mod}`macos.camera` lists the cameras, takes photos and records videos with
the webcam, like Photo Booth.

```python
import macos

[camera.name for camera in macos.camera.devices()]   # ['FaceTime HD Camera']
macos.camera.photo("me.jpg")
macos.camera.record("hello.mov", seconds=5)
```

Photos and videos need the [Camera permission](permissions.md#camera-and-microphone),
which macOS asks for the first time.
{func}`~macos.camera.has_permission` tells whether it's granted without asking;
{func}`~macos.camera.request_permission` asks. The camera's green light is on
while it works.

## Cameras

{func}`~macos.camera.devices` returns the connected cameras, the default one
first: the built-in one, USB webcams, an iPhone through Continuity. Each
{class}`~macos.camera.Camera` has its `name`, a stable `id`, and whether it
`is_default`. Listing them needs no permission and doesn't turn a camera on.

## Photos

```python
macos.camera.photo("me.jpg")                       # the default camera
macos.camera.photo("desk.png", camera="Logitech")  # another one, by name
path = macos.camera.photo()                        # a temporary .jpg, yours to delete
```

The extension sets the format: `.jpg`, `.png`, `.heic` or `.tiff`. The camera
turns on for about a second before the photo, so the exposure settles.
`camera` is a {class}`~macos.camera.Camera`, its `id`, or its name, or part of
it when only one camera matches.

## Videos

```python
macos.camera.record("hello.mov", 5)                              # with the sound
macos.camera.record("silent.mov", 5, audio=False)                # without it
macos.video.convert("hello.mov", "hello.mp4", quality="medium")
```

{func}`~macos.camera.record` returns when the recording ends. It records a
`.mov`; {func}`macos.video.convert` makes it an `.mp4` or smaller. With sound,
it also records the default microphone, which needs the Microphone permission.

It records beside the file and moves the video in place once saved: if the
recording fails, a file that was already there stays as it was.

The camera reports back on the main thread's run loop, which these functions
turn while they wait: call {func}`~macos.camera.photo` and
{func}`~macos.camera.record` from the main thread. From another one they raise
{class}`~macos.MacOSError`, instead of waiting for a photo that never comes.

To know whether an app is using the camera right now, see
{func}`macos.system.camera_in_use`.

## Reference

- {func}`macos.camera.devices`
- {func}`macos.camera.photo`
- {func}`macos.camera.record`
- {class}`macos.camera.Camera`
- {func}`macos.camera.has_permission`
- {func}`macos.camera.request_permission`
