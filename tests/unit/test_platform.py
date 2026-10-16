"""Unit tests for platform guards: NotSupportedError outside macOS."""

import inspect
import sys
from datetime import datetime
from pathlib import Path

import pytest

import macos
from macos import _system


def test_missing_command_raises_not_supported(fake_run, monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(_system.subprocess, "run", missing)

    with pytest.raises(macos.NotSupportedError, match="'say' command was not found"):
        macos.say("x")


def test_other_platforms_raise_not_supported(monkeypatch):
    monkeypatch.setattr(_system.sys, "platform", "linux")

    with pytest.raises(macos.NotSupportedError, match="only works on macOS"):
        macos.say("x")


def _call_id(call):
    """The call a lambda below makes, as the test's id: ``macos.say("x")``, not ``<lambda>1``."""
    return inspect.getsource(call).strip().split("\n")[0].replace("lambda: ", "", 1).rstrip(",")


@pytest.mark.skipif(sys.platform == "darwin", reason="checks behaviour outside macOS")
@pytest.mark.parametrize(
    "call",
    [
        lambda: macos.notify("x"),
        lambda: macos.say("x"),
        lambda: macos.say("x", wait=False),
        lambda: macos.speech.voices(),
        lambda: macos.screenshot(),
        lambda: macos.screen.has_permission(),
        lambda: macos.clipboard.copy("x"),
        lambda: macos.clipboard.paste(),
        lambda: macos.appearance.is_dark(),
        lambda: macos.apps.running(),
        lambda: macos.apps.frontmost(),
        lambda: macos.apps.get("Safari"),
        lambda: macos.apps.open("Safari"),
        lambda: macos.apps.App("Safari", None, 1, None).quit(),
        lambda: macos.keychain.get("service", "account"),
        lambda: macos.keychain.set("service", "account", "password"),
        lambda: macos.power.battery(),
        lambda: macos.power.keep_awake().__enter__(),
        lambda: macos.shortcuts.list(),
        lambda: macos.shortcuts.run("Shortcut"),
        lambda: macos.finder.tags(__file__),
        lambda: macos.finder.trash(__file__),
        lambda: macos.finder.reveal(__file__),
        lambda: macos.clipboard.copy_image(b"image"),
        lambda: macos.clipboard.paste_image(),
        lambda: macos.notifications.is_allowed(),
        lambda: macos.volume.get(),
        lambda: macos.volume.set(10),
        lambda: macos.volume.mute(),
        lambda: macos.spotlight.search("kind:pdf"),
        lambda: macos.spotlight.search_name("report"),
        lambda: macos.spotlight.metadata(__file__),
        lambda: macos.dialog.alert("x"),
        lambda: macos.dialog.confirm("x"),
        lambda: macos.dialog.prompt("x"),
        lambda: macos.dialog.choose(["a"]),
        lambda: macos.dialog.choose_file(),
        lambda: macos.system.version(),
        lambda: macos.system.model_identifier(),
        lambda: macos.system.uptime(),
        lambda: macos.system.idle_time(),
        lambda: macos.screen.displays(),
        lambda: macos.power.sleep(),
        lambda: macos.keychain.accounts("service"),
        lambda: macos.say("x", output="speech.aiff"),
        lambda: macos.vision.text(b"image"),
        lambda: macos.vision.languages(),
        lambda: macos.screen.wallpaper(),
        lambda: macos.screen.set_wallpaper(__file__),
        lambda: macos.open("https://python.org"),
        lambda: macos.open_with(__file__, "Preview"),
        lambda: macos.apps.default_for("pdf"),
        lambda: macos.apps.default_browser(),
        lambda: macos.clipboard.copy_files([__file__]),
        lambda: macos.clipboard.paste_files(),
        lambda: macos.finder.thumbnail(__file__),
        lambda: macos.finder.is_alias(__file__),
        lambda: macos.finder.resolve_alias(__file__),
        lambda: macos.finder.make_alias(__file__, "elsewhere"),
        lambda: macos.video.info(__file__),
        lambda: macos.video.frame(__file__),
        lambda: macos.video.convert(__file__, "out.mp4"),
        lambda: macos.screen.record("out.mov", 1),
        lambda: macos.windows.list(),
        lambda: macos.windows.focused(),
        lambda: macos.windows.has_permission(),
        lambda: macos.hotkeys.run(timeout=0.1),
        lambda: macos.hotkeys.wait("f19", timeout=0.1),
        lambda: macos.hotkeys.has_permission(),
        lambda: macos.music.now_playing(),
        lambda: macos.music.play(),
        lambda: macos.vision.horizon(b"image"),
        lambda: macos.image.straighten(__file__, "out.png"),
        lambda: macos.pdf.watermark(__file__, "out.pdf", "DRAFT"),
        lambda: macos.pdf.compress(__file__, "out.pdf"),
        lambda: macos.pdf.grayscale(__file__, "out.pdf"),
        lambda: macos.video.to_gif(__file__, "out.gif"),
        lambda: macos.music.volume(),
        lambda: macos.music.set_volume(50),
        lambda: macos.music.seek(10),
        lambda: macos.camera.devices(),
        lambda: macos.camera.photo(),
        lambda: macos.camera.record("out.mov", 1),
        lambda: macos.camera.has_permission(),
        lambda: macos.camera.request_permission(),
        lambda: macos.audio.record("out.m4a", 1),
        lambda: macos.audio.input_level(),
        lambda: macos.audio.has_permission(),
        lambda: macos.audio.request_permission(),
        lambda: macos.system.volumes(),
        lambda: macos.system.eject("Backup"),
        lambda: macos.image.info(__file__),
        lambda: macos.image.convert(__file__, "out.png"),
        lambda: macos.image.qr_code("x"),
        lambda: macos.pdf.page_count(__file__),
        lambda: macos.pdf.text(__file__),
        lambda: macos.vision.barcodes(b"image"),
        lambda: macos.vision.classify(b"image"),
        lambda: macos.vision.faces(b"image"),
        lambda: macos.language.detect("Olá"),
        lambda: macos.language.sentiment("Olá"),
        lambda: macos.vision.remove_background(b"image"),
        lambda: macos.vision.animals(b"image"),
        lambda: macos.audio.outputs(),
        lambda: macos.audio.default_output(),
        lambda: macos.audio.set_output("Speakers"),
        lambda: macos.language.similarity("car", "automobile"),
        lambda: macos.language.embedding("hello"),
        lambda: macos.language.entities("Tim Cook"),
        lambda: macos.language.keywords("battery life"),
        lambda: macos.sound.play("Glass"),
        lambda: macos.sound.beep(),
        lambda: macos.sound.names(),
        lambda: macos.network.is_online(),
        lambda: macos.network.ip(),
        lambda: macos.network.wifi_power(),
        lambda: macos.network.set_wifi_power(True),
        lambda: macos.appearance.wait_for_change(timeout=0.1),
        lambda: macos.appearance.accent_color(),
        lambda: macos.image.metadata(__file__),
        lambda: macos.image.taken_at(__file__),
        lambda: macos.image.location(__file__),
        lambda: macos.image.strip_metadata(__file__, "out.jpg"),
        lambda: macos.pdf.from_images([__file__], "out.pdf"),
        lambda: macos.vision.scan_document(b"image"),
        lambda: macos.vision.image_distance(b"image", b"image"),
        lambda: macos.vision.duplicates([b"image", b"image"]),
        lambda: macos.vision.smart_crop(b"image", 100, 100),
        lambda: macos.system.fonts(),
        lambda: macos.screen.start_screensaver(),
        lambda: macos.image.set_taken_at(__file__, datetime(2024, 5, 1)),
        lambda: macos.image.set_location(__file__, 0.0, 0.0),
        lambda: macos.image.crop(__file__, "out.png", (0, 0, 1, 1)),
        lambda: macos.image.rotate(__file__, "out.png", 90),
        lambda: macos.image.flip(__file__, "out.png"),
        lambda: macos.image.blur_faces(__file__, "out.png"),
        lambda: macos.image.dominant_colors(__file__),
        lambda: macos.vision.best_shot([b"image"]),
        lambda: macos.pdf.metadata(__file__),
        lambda: macos.pdf.rotate(__file__, "out.pdf", 90),
        lambda: macos.pdf.encrypt(__file__, "out.pdf", "secret"),
        lambda: macos.keyboard.type("x"),
        lambda: macos.keyboard.press("enter"),
        lambda: macos.keyboard.has_permission(),
        lambda: macos.keyboard.has_listen_permission(),
        lambda: macos.keyboard.request_listen_permission(),
        lambda: macos.mouse.has_listen_permission(),
        lambda: macos.mouse.request_listen_permission(),
        lambda: macos.keyboard.brightness(),
        lambda: macos.keyboard.set_brightness(0.5),
        lambda: macos.keyboard.auto_brightness(),
        lambda: macos.keyboard.set_auto_brightness(True),
        lambda: macos.mouse.position(),
        lambda: macos.mouse.move(1, 1),
        lambda: macos.mouse.click(),
        lambda: macos.mouse.drag(1, 1),
        lambda: macos.mouse.scroll(1),
        lambda: macos.screen.brightness(),
        lambda: macos.screen.set_brightness(0.5),
        lambda: macos.bluetooth.power(),
        lambda: macos.bluetooth.set_power(True),
        lambda: macos.bluetooth.devices(),
        lambda: macos.bluetooth.connect("AirPods"),
        lambda: macos.bluetooth.disconnect("AirPods"),
        lambda: macos.keyboard.hold("shift").__enter__(),
        lambda: macos.keyboard.layouts(),
        lambda: macos.keyboard.layout(),
        lambda: macos.keyboard.set_layout("ABC"),
        lambda: macos.screen.night_shift(),
        lambda: macos.screen.set_night_shift(True),
        lambda: macos.appearance.set_mode("dark"),
        lambda: macos.system.thermal_state(),
        lambda: macos.system.lid_closed(),
        lambda: macos.system.camera_in_use(),
        lambda: macos.system.microphone_in_use(),
        lambda: macos.power.low_power_mode(),
        lambda: macos.screen.lock(),
        lambda: macos.screen.true_tone(),
        lambda: macos.screen.set_true_tone(True),
        lambda: macos.screen.is_locked(),
        lambda: macos.screen.is_asleep(),
        lambda: macos.keyboard.caps_lock(),
        lambda: macos.audio.input_volume(),
        lambda: macos.audio.set_input_volume(0.5),
        lambda: macos.audio.input_muted(),
        lambda: macos.audio.mute_input(),
        lambda: macos.audio.info(__file__),
        lambda: macos.audio.convert(__file__, "out.m4a"),
        lambda: macos.audio.trim(__file__, "out.m4a", 1),
        lambda: macos.audio.concat([__file__], "out.m4a"),
        lambda: macos.audio.fade(__file__, "out.m4a", fade_in=1),
        lambda: macos.audio.gain(__file__, "out.m4a", 3),
        lambda: macos.audio.reverse(__file__, "out.m4a"),
        lambda: macos.audio.speed(__file__, "out.m4a", 1.5),
        lambda: macos.audio.classify(__file__),
        lambda: macos.audio.record_until_silence("out.m4a"),
        lambda: macos.image.enhance(__file__, "out.png"),
        lambda: macos.image.effect(__file__, "out.png", "noir"),
        lambda: macos.image.blur_background(__file__, "out.png"),
        lambda: macos.image.replace_background(__file__, __file__, "out.png"),
        lambda: macos.image.watermark(__file__, "out.png", "draft"),
        lambda: macos.image.contact_sheet([__file__], "out.png"),
        lambda: macos.vision.aesthetics(b"image"),
        lambda: macos.vision.body_pose(b"image"),
        lambda: macos.vision.hand_pose(b"image"),
        lambda: macos.video.trim(__file__, "out.mov", 1),
        lambda: macos.video.concat([__file__], "out.mov"),
        lambda: macos.video.speed(__file__, "out.mov", 2),
        lambda: macos.video.rotate(__file__, "out.mov", 90),
        lambda: macos.video.crop(__file__, "out.mov", (0, 0, 10, 10)),
        lambda: macos.video.reverse(__file__, "out.mov"),
        lambda: macos.video.mute(__file__, "out.mov"),
        lambda: macos.video.add_audio(__file__, __file__, "out.mov"),
        lambda: macos.video.add_language_track(__file__, __file__, "out.mov", "en"),
        lambda: macos.video.from_images([__file__], "out.mov"),
        lambda: macos.video.frames(__file__),
        lambda: next(macos.finder.watch(Path(__file__).parent)),
        lambda: macos.finder.wait_for_change(Path(__file__).parent, timeout=0),
        lambda: macos.events.wait("wake", timeout=0),
        lambda: macos.schedule.add("job", __file__, every=60),
        lambda: macos.schedule.jobs(),
        lambda: macos.schedule.add("job", __file__, when_changed=Path(__file__).parent),
        lambda: macos.time_machine.exclude(__file__),
        lambda: macos.time_machine.include(__file__),
        lambda: macos.time_machine.is_excluded(__file__),
        lambda: macos.power.sleep_blockers(),
        lambda: macos.network.vpns(),
        lambda: macos.network.bandwidth(0.01),
        lambda: macos.network.connect_vpn("Office"),
        lambda: macos.network.disconnect_vpn("Office"),
        lambda: macos.apps.uninstall("Slack", dry_run=True),
        lambda: macos.document.convert(__file__, "out.pdf"),
        lambda: macos.document.text(__file__),
        lambda: macos.schedule.remove("job"),
        lambda: macos.browser.tabs(),
        lambda: macos.browser.open("https://example.com"),
        lambda: macos.screen.find_text("Submit"),
        lambda: macos.screen.color_at(1, 1),
        lambda: macos.mouse.click_text("Submit"),
        lambda: macos.finder.selection(),
        lambda: macos.finder.current_folder(),
        lambda: next(macos.clipboard.watch(timeout=0, include_sensitive=True)),
        lambda: macos.system.wait_for_idle(1),
        lambda: macos.windows.wait_for(timeout=0),
        lambda: next(macos.keyboard.watch(timeout=0)),
        lambda: next(macos.mouse.watch(timeout=0)),
        lambda: macos.defaults.read("com.apple.dock", "autohide"),
        lambda: macos.defaults.write("com.example.app", "key", 1),
        lambda: macos.dock.apps(),
        lambda: macos.dock.set_autohide(True),
        lambda: macos.finder.set_show_hidden_files(True),
        lambda: macos.screen.screenshot_folder(),
        lambda: macos.system.mount_image(__file__),
        lambda: macos.system.available_updates(),
        lambda: macos.system.cpu_usage(0.01),
        lambda: macos.system.memory_usage(),
        lambda: macos.apps.login_items(),
        lambda: macos.apps.set_default_for("txt", "TextEdit"),
        lambda: macos.time_machine.is_backing_up(),
        lambda: macos.time_machine.last_backup(),
        lambda: macos.auth.is_available(),
        lambda: macos.auth.confirm("test"),
        lambda: macos.finder.compress(__file__),
        lambda: macos.finder.quick_look(__file__),
        lambda: macos.pdf.ocr(__file__, "out.pdf"),
        lambda: macos.pdf.redact(__file__, "out.pdf", "secret"),
        lambda: macos.keyboard.key_repeat(),
        lambda: macos.keyboard.set_key_repeat(0.03),
        lambda: macos.keyboard.set_autocorrect(False),
        lambda: macos.trackpad.set_tap_to_click(True),
        lambda: macos.trackpad.natural_scrolling(),
        lambda: macos.mouse.set_tracking_speed(0.5),
        lambda: macos.dock.set_hot_corner("top_left", None),
        lambda: macos.dock.magnification(),
        lambda: macos.finder.set_default_view("list"),
        lambda: macos.finder.set_show_library_folder(True),
        lambda: macos.finder.show_library_folder(),
        lambda: macos.appearance.set_accent_color("blue"),
        lambda: macos.appearance.set_hide_menu_bar(False),
        lambda: macos.screen.screensaver_delay(),
        lambda: macos.system.set_ds_store_on_network(False),
        lambda: macos.system.set_show_battery_percentage(True),
        lambda: macos.auth.required("test")(lambda: None)(),
        lambda: macos.keyboard.set_full_keyboard_access(True),
        lambda: macos.keyboard.remap("caps_lock", "escape"),
        lambda: macos.keyboard.remappings(),
        lambda: macos.trackpad.set_secondary_click(None),
        lambda: macos.mouse.set_double_click_speed(0.5),
        lambda: macos.dock.add_spacer(),
        lambda: macos.dock.separate_spaces_per_display(),
        lambda: macos.finder.drives_on_desktop(),
        lambda: macos.windows.set_tiling(True),
        lambda: macos.appearance.scroll_bars(),
        lambda: macos.screen.set_screenshot_thumbnail(True),
        lambda: macos.system.clock_format(),
        lambda: macos.defaults.restored("com.apple.dock").__enter__(),
        lambda: macos.keyboard.set_fn_key_action(None),
        lambda: macos.keyboard.app_shortcuts("com.apple.Safari"),
        lambda: macos.keyboard.set_system_shortcut("spotlight", False),
        lambda: macos.keyboard.backlight_timeout(),
        lambda: macos.trackpad.gestures(),
        lambda: macos.trackpad.set_click_pressure("light"),
        lambda: macos.mouse.set_acceleration(False),
        lambda: macos.dock.set_dim_hidden_apps(True),
        lambda: macos.dock.folders(),
        lambda: macos.finder.desktop_view(),
        lambda: macos.finder.set_quit_menu(True),
        lambda: macos.windows.set_animations(False),
        lambda: macos.appearance.font_smoothing(),
        lambda: macos.sound.set_alert_sound("Funk"),
        lambda: macos.screen.screenshot_target(),
        lambda: macos.screen.night_shift_schedule(),
        lambda: macos.screen.display_modes(),
        lambda: macos.screen.set_main_display(1),
        lambda: macos.screen.stop_mirroring(),
        lambda: macos.system.security_status(),
        lambda: macos.system.menu_bar_items(),
        lambda: macos.system.measurement_units(),
        lambda: macos.apps.is_quarantined(__file__),
        lambda: macos.printer.printers(),
        lambda: macos.printer.print_file(__file__),
        lambda: macos.settings.export(),
        lambda: macos.settings.apply({}),
        lambda: macos.maps.geocode("Paris"),
        lambda: macos.maps.reverse_geocode(48.8, 2.3),
        lambda: macos.system.processes(),
        lambda: macos.system.process(1),
        lambda: macos.system.kill(99999),
        lambda: macos.system.processes(cpu=True),
        lambda: macos.system.ports(),
        lambda: macos.system.port_owner(8000),
        lambda: macos.system.connections(),
        lambda: macos.system.open_files(1),
        lambda: macos.system.who_uses(__file__),
        lambda: macos.network.speed_test(),
        lambda: macos.system.network_usage(),
        lambda: macos.system.energy_usage(),
        lambda: macos.system.gpu_usage(),
        lambda: macos.system.disk_health(),
        lambda: macos.pdf.form_fields(__file__),
        lambda: macos.pdf.fill_form(__file__, "out.pdf", {}),
        lambda: macos.pdf.sign(__file__, "out.pdf", __file__),
        lambda: macos.pdf.add_text(__file__, "out.pdf", "text"),
        lambda: macos.network.wifi_signal(),
        lambda: macos.apps.installed(),
        lambda: macos.system.crash_reports(),
        lambda: macos.system.logs(),
        lambda: macos.pdf.bookmarks(__file__),
        lambda: macos.pdf.set_bookmarks(__file__, "out.pdf", []),
        lambda: macos.pdf.images(__file__, "out"),
        lambda: macos.system.startup_items(),
        lambda: macos.system.usb_devices(),
        lambda: macos.power.adapter(),
        lambda: macos.network.interfaces(),
        lambda: macos.network.dns_servers(),
        lambda: macos.network.proxies(),
        lambda: macos.finder.largest(Path(__file__).parent),
        lambda: macos.maps.open("Paris"),
        lambda: macos.maps.directions("Paris"),
        lambda: macos.finder.set_icon(__file__, __file__),
        lambda: macos.finder.remove_icon(__file__),
        lambda: macos.finder.has_custom_icon(__file__),
        lambda: macos.apps.add_login_item("Safari"),
        lambda: macos.apps.remove_login_item("Safari"),
        lambda: macos.audio.set_input("Built-in"),
        lambda: macos.browser.run_js("1 + 1"),
        lambda: macos.defaults.delete("com.apple.dock", "autohide"),
        lambda: macos.defaults.keys("com.apple.dock"),
        lambda: macos.dock.add_app("Safari"),
        lambda: macos.dock.remove_app("Safari"),
        lambda: macos.dock.set_autohide_delay(0.5),
        lambda: macos.dock.set_autohide_duration(None),
        lambda: macos.dock.remove_folder(Path(__file__).parent),
        lambda: macos.hotkeys.register("ctrl+option+s", lambda: None),
        lambda: macos.hotkeys.unregister("ctrl+option+s"),
        lambda: macos.keyboard.set_app_shortcut("Safari", "Reload Page", "cmd+shift+r"),
        lambda: macos.keyboard.set_backlight_timeout(None),
        lambda: macos.keychain.delete("service", "account"),
        lambda: macos.language.guess("hello"),
        lambda: macos.mouse.set_scroll_speed(0.5),
        lambda: macos.pdf.merge([__file__], "out.pdf"),
        lambda: macos.pdf.render(__file__),
        lambda: macos.printer.set_default("Office"),
        lambda: macos.printer.cancel(1),
        lambda: macos.schedule.get("backup"),
        lambda: macos.schedule.run_now("backup"),
        lambda: macos.schedule.pause("backup"),
        lambda: macos.schedule.resume("backup"),
        lambda: macos.screen.wait_for_text("x", timeout=0),
        lambda: macos.screen.set_screensaver_delay(None),
        lambda: macos.screen.set_screenshot_name(None),
        lambda: macos.screen.set_night_shift_schedule(None),
        lambda: macos.screen.set_night_shift_strength(0.5),
        lambda: macos.screen.set_display_mode(1920, 1080),
        lambda: macos.screen.mirror(1),
        lambda: macos.sound.set_alert_volume(0.5),
        lambda: macos.system.unmount_image(Path(__file__).parent),
        lambda: macos.system.set_menu_bar_spacing(None),
        lambda: macos.trackpad.set_tracking_speed(0.5),
        lambda: macos.vision.lines(__file__),
        lambda: macos.windows.tile([]),
    ],
    ids=_call_id,
)
def test_every_feature_raises_not_supported_outside_macos(call):
    with pytest.raises(macos.NotSupportedError):
        call()


def test_missing_private_classes_are_not_supported(monkeypatch):
    from contextlib import nullcontext

    def missing(name):
        raise LookupError("Objective-C class {!r} is not loaded".format(name))

    monkeypatch.setattr(macos._objc, "cls", missing)
    monkeypatch.setattr(macos._objc, "autorelease_pool", nullcontext)
    for module in (macos.keyboard, macos.screen):
        monkeypatch.setattr(module, "private_framework", lambda name: None)
        monkeypatch.setattr(module, "framework", lambda name: None)

    with pytest.raises(macos.NotSupportedError, match="keyboard backlight"):
        macos.keyboard.brightness()
    with pytest.raises(macos.NotSupportedError, match="Night Shift"):
        macos.screen.night_shift()
    with pytest.raises(macos.NotSupportedError, match="True Tone"):
        macos.screen.true_tone()


# The public functions the list above doesn't call. Those that take no required argument are called
# below, outside macOS, and must raise all the same. The others need an argument the test can't make
# up, and check it before the platform: a valid one reaches the guard, which the live tests show.
_PURE_PYTHON = {
    "events.stop",  # a flag, read by run()
    "hotkeys.stop",
    "menubar.every",  # a Timer, read by run()
    "menubar.quit",
    "settings.batch",  # a context manager, around calls that are guarded themselves
    "settings.names",  # a table
}
_ARGUMENTS_CHECKED_FIRST = {
    "appearance.set_scroll_bars",
    "apps.install_from_dmg",
    "apps.open_with",
    "apps.unquarantine",
    "dock.add_folder",
    "dock.set_magnification",
    "dock.set_minimize_effect",
    "dock.set_position",
    "dock.set_size",
    "events.off",
    "events.on",
    "events.run",
    "finder.add_tags",
    "finder.extract",
    "finder.remove_tags",
    "finder.set_desktop_view",
    "finder.set_new_window_folder",
    "finder.set_search_scope",
    "finder.set_show_drives_on_desktop",
    "finder.set_tags",
    "image.resize",
    "pdf.extract",
    "screen.set_screenshot_folder",
    "screen.set_screenshot_format",
    "screen.set_screenshot_target",
    "system.set_clock_format",
    "system.set_measurement_units",
    "system.set_menu_bar_items",
    "system.set_temperature_unit",
    "trackpad.set_gesture",
    "windows.set_double_click_title_bar",
}


def _listed_calls():
    """The ``module.function`` names the parametrized test above calls."""
    import re

    source = Path(__file__).read_text()
    return set(re.findall(r"macos\.([a-z_]+\.[A-Za-z_]+)\(", source)) | {
        "{}.{}".format(macos._SHORTCUTS[name], name) for name in re.findall(r"lambda: macos\.([a-z_]+)\(", source)
    }


def _public_functions():
    """Every ``(module.function, function)`` in a submodule's ``__all__``."""
    import importlib

    found = []
    for module in sorted(macos._SUBMODULES):
        loaded = importlib.import_module("macos." + module)
        for name in loaded.__all__:
            function = getattr(loaded, name)
            if inspect.isfunction(function):
                found.append(("{}.{}".format(module, name), function))
    return found


def _required_arguments(function):
    return [
        parameter.name
        for parameter in inspect.signature(function).parameters.values()
        if parameter.default is inspect.Parameter.empty and parameter.kind is not inspect.Parameter.KEYWORD_ONLY
    ]


def test_every_public_function_is_accounted_for():
    """A new public function is either called above, or named here with why it can't be."""
    listed = _listed_calls() | _PURE_PYTHON | _ARGUMENTS_CHECKED_FIRST
    unaccounted = [name for name, function in _public_functions() if name not in listed and _required_arguments(function)]
    assert not unaccounted, "add a call to the list above, or the name to _ARGUMENTS_CHECKED_FIRST: {}".format(unaccounted)
    stale = sorted((_PURE_PYTHON | _ARGUMENTS_CHECKED_FIRST) - {name for name, _ in _public_functions()})
    assert not stale, "no longer public: {}".format(stale)
    listed_too = sorted(_ARGUMENTS_CHECKED_FIRST & _listed_calls())
    assert not listed_too, "called above already: {}".format(listed_too)


@pytest.mark.skipif(sys.platform == "darwin", reason="checks behaviour outside macOS")
@pytest.mark.parametrize(
    "name, function",
    [
        (name, function)
        for name, function in _public_functions()
        if not _required_arguments(function) and name not in _PURE_PYTHON
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_every_other_feature_raises_not_supported_outside_macos(name, function):
    if name in _listed_calls() or name in _ARGUMENTS_CHECKED_FIRST:
        pytest.skip("called in the list above, or checks its arguments first")
    with pytest.raises(macos.NotSupportedError):
        result = function()
        if inspect.isgenerator(result):
            next(result)
