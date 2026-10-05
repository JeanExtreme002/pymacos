# API

The complete public API, generated from the source code. The feature pages
explain how to use each part.

## Top-level functions

```{eval-rst}
.. autofunction:: macos.open
.. autofunction:: macos.open_with
.. autofunction:: macos.notify
.. autofunction:: macos.say
.. autofunction:: macos.screenshot
```

## macos.appearance

```{eval-rst}
.. module:: macos.appearance

.. autofunction:: macos.appearance.accent_color
.. autofunction:: macos.appearance.set_accent_color
.. autodata:: macos.appearance.ACCENT_COLORS
.. autofunction:: macos.appearance.set_auto_mode
.. autofunction:: macos.appearance.font_smoothing
.. autofunction:: macos.appearance.set_font_smoothing
.. autofunction:: macos.appearance.set_hide_menu_bar
.. autofunction:: macos.appearance.is_auto
.. autofunction:: macos.appearance.is_dark
.. autofunction:: macos.appearance.menu_bar_hidden
.. autofunction:: macos.appearance.mode
.. autofunction:: macos.appearance.set_mode
.. autofunction:: macos.appearance.scroll_bars
.. autofunction:: macos.appearance.set_scroll_bars
.. autofunction:: macos.appearance.wait_for_change
```

## macos.apps

```{eval-rst}
.. module:: macos.apps

.. autofunction:: macos.apps.add_login_item
.. autoclass:: macos.apps.App
   :members: is_running, is_active, is_hidden, activate, hide, unhide, quit
.. autofunction:: macos.apps.default_browser
.. autofunction:: macos.apps.default_for
.. autofunction:: macos.apps.set_default_for
.. autofunction:: macos.apps.frontmost
.. autofunction:: macos.apps.get
.. autofunction:: macos.apps.installed
.. autoclass:: macos.apps.InstalledApp
.. autofunction:: macos.apps.install_from_dmg
.. autofunction:: macos.apps.is_quarantined
.. autoclass:: macos.apps.LoginItem
.. autofunction:: macos.apps.login_items
.. autofunction:: macos.apps.open
.. autofunction:: macos.apps.open_with
.. autofunction:: macos.apps.remove_login_item
.. autofunction:: macos.apps.running
.. autofunction:: macos.apps.uninstall
.. autofunction:: macos.apps.unquarantine
```

## macos.audio

```{eval-rst}
.. module:: macos.audio

.. autoclass:: macos.audio.AudioInfo
.. autofunction:: macos.audio.classify
.. autofunction:: macos.audio.concat
.. autofunction:: macos.audio.convert
.. autofunction:: macos.audio.default_input
.. autofunction:: macos.audio.default_output
.. autoclass:: macos.audio.Device
.. autofunction:: macos.audio.devices
.. autofunction:: macos.audio.fade
.. autofunction:: macos.audio.gain
.. autofunction:: macos.audio.has_permission
.. autofunction:: macos.audio.info
.. autofunction:: macos.audio.set_input
.. autofunction:: macos.audio.input_level
.. autofunction:: macos.audio.input_muted
.. autofunction:: macos.audio.inputs
.. autofunction:: macos.audio.input_volume
.. autofunction:: macos.audio.set_input_volume
.. autofunction:: macos.audio.mute_input
.. autofunction:: macos.audio.set_output
.. autofunction:: macos.audio.outputs
.. autofunction:: macos.audio.record
.. autofunction:: macos.audio.record_until_silence
.. autofunction:: macos.audio.request_permission
.. autofunction:: macos.audio.reverse
.. autofunction:: macos.audio.speed
.. autofunction:: macos.audio.trim
```

## macos.auth

```{eval-rst}
.. module:: macos.auth

.. autofunction:: macos.auth.confirm
.. autofunction:: macos.auth.is_available
.. autofunction:: macos.auth.required
```

## macos.bluetooth

```{eval-rst}
.. module:: macos.bluetooth

.. autofunction:: macos.bluetooth.connect
.. autoclass:: macos.bluetooth.Device
.. autofunction:: macos.bluetooth.devices
.. autofunction:: macos.bluetooth.disconnect
.. autofunction:: macos.bluetooth.power
.. autofunction:: macos.bluetooth.set_power
```

## macos.browser

```{eval-rst}
.. module:: macos.browser

.. autodata:: macos.browser.BROWSERS
   :no-value:
.. autofunction:: macos.browser.current_tab
.. autofunction:: macos.browser.open
.. autofunction:: macos.browser.run_js
.. autoclass:: macos.browser.Tab
   :members: activate, close, reload, go
.. autofunction:: macos.browser.tabs
```

## macos.camera

```{eval-rst}
.. module:: macos.camera

.. autoclass:: macos.camera.Camera
.. autofunction:: macos.camera.devices
.. autofunction:: macos.camera.has_permission
.. autofunction:: macos.camera.photo
.. autofunction:: macos.camera.record
.. autofunction:: macos.camera.request_permission
```

## macos.clipboard

```{eval-rst}
.. module:: macos.clipboard

.. autofunction:: macos.clipboard.change_count
.. autofunction:: macos.clipboard.clear
.. autofunction:: macos.clipboard.copy
.. autofunction:: macos.clipboard.copy_files
.. autofunction:: macos.clipboard.copy_image
.. autofunction:: macos.clipboard.has_image
.. autofunction:: macos.clipboard.paste
.. autofunction:: macos.clipboard.paste_files
.. autofunction:: macos.clipboard.paste_image
.. autofunction:: macos.clipboard.wait_for_change
.. autofunction:: macos.clipboard.watch
```

## macos.defaults

```{eval-rst}
.. module:: macos.defaults

.. autofunction:: macos.defaults.delete
.. autodata:: macos.defaults.GLOBAL
.. autofunction:: macos.defaults.keys
.. autofunction:: macos.defaults.read
.. autofunction:: macos.defaults.restored
.. autofunction:: macos.defaults.write
```

## macos.dialog

```{eval-rst}
.. module:: macos.dialog

.. autofunction:: macos.dialog.alert
.. autofunction:: macos.dialog.choose
.. autofunction:: macos.dialog.choose_file
.. autofunction:: macos.dialog.choose_files
.. autofunction:: macos.dialog.choose_folder
.. autofunction:: macos.dialog.confirm
.. autofunction:: macos.dialog.prompt
```

## macos.dock

```{eval-rst}
.. module:: macos.dock

.. autofunction:: macos.dock.add_app
.. autofunction:: macos.dock.add_folder
.. autofunction:: macos.dock.add_spacer
.. autofunction:: macos.dock.apps
.. autofunction:: macos.dock.autohide
.. autofunction:: macos.dock.set_autohide
.. autofunction:: macos.dock.autohide_delay
.. autofunction:: macos.dock.set_autohide_delay
.. autofunction:: macos.dock.autohide_duration
.. autofunction:: macos.dock.set_autohide_duration
.. autofunction:: macos.dock.auto_rearrange_spaces
.. autofunction:: macos.dock.set_auto_rearrange_spaces
.. autofunction:: macos.dock.dim_hidden_apps
.. autofunction:: macos.dock.set_dim_hidden_apps
.. autoclass:: macos.dock.DockApp
.. autoclass:: macos.dock.DockFolder
.. autofunction:: macos.dock.folders
.. autofunction:: macos.dock.group_windows_by_app
.. autofunction:: macos.dock.set_group_windows_by_app
.. autofunction:: macos.dock.set_hot_corner
.. autodata:: macos.dock.HOT_CORNER_ACTIONS
.. autofunction:: macos.dock.hot_corner_modifiers
.. autofunction:: macos.dock.hot_corners
.. autofunction:: macos.dock.launch_animation
.. autofunction:: macos.dock.set_launch_animation
.. autofunction:: macos.dock.magnification
.. autofunction:: macos.dock.set_magnification
.. autofunction:: macos.dock.minimize_effect
.. autofunction:: macos.dock.set_minimize_effect
.. autofunction:: macos.dock.minimize_to_app
.. autofunction:: macos.dock.set_minimize_to_app
.. autofunction:: macos.dock.only_open_apps
.. autofunction:: macos.dock.set_only_open_apps
.. autofunction:: macos.dock.position
.. autofunction:: macos.dock.set_position
.. autofunction:: macos.dock.remove_app
.. autofunction:: macos.dock.remove_folder
.. autofunction:: macos.dock.remove_spacers
.. autofunction:: macos.dock.restart
.. autofunction:: macos.dock.separate_spaces_per_display
.. autofunction:: macos.dock.set_separate_spaces_per_display
.. autofunction:: macos.dock.show_indicators
.. autofunction:: macos.dock.set_show_indicators
.. autofunction:: macos.dock.show_recents
.. autofunction:: macos.dock.set_show_recents
.. autofunction:: macos.dock.size
.. autofunction:: macos.dock.set_size
.. autofunction:: macos.dock.switch_to_space_with_app
.. autofunction:: macos.dock.set_switch_to_space_with_app
```

## macos.document

```{eval-rst}
.. module:: macos.document

.. autofunction:: macos.document.convert
.. autofunction:: macos.document.text
```

## macos.events

```{eval-rst}
.. module:: macos.events

.. autoclass:: macos.events.Event
.. autoclass:: macos.events.Handler
   :members: remove
.. autodata:: macos.events.NAMES
   :no-value:
.. autofunction:: macos.events.off
.. autofunction:: macos.events.on
.. autofunction:: macos.events.run
.. autofunction:: macos.events.stop
.. autofunction:: macos.events.wait
```

## macos.finder

```{eval-rst}
.. module:: macos.finder

.. autofunction:: macos.finder.add_tags
.. autofunction:: macos.finder.compress
.. autofunction:: macos.finder.current_folder
.. autofunction:: macos.finder.default_view
.. autofunction:: macos.finder.set_default_view
.. autofunction:: macos.finder.desktop_view
.. autofunction:: macos.finder.set_desktop_view
.. autofunction:: macos.finder.drives_on_desktop
.. autoclass:: macos.finder.Event
.. autofunction:: macos.finder.extension_change_warning
.. autofunction:: macos.finder.set_extension_change_warning
.. autofunction:: macos.finder.extract
.. autofunction:: macos.finder.folders_first
.. autofunction:: macos.finder.set_folders_first
.. autofunction:: macos.finder.has_custom_icon
.. autofunction:: macos.finder.set_icon
.. autofunction:: macos.finder.is_alias
.. autofunction:: macos.finder.largest
.. autofunction:: macos.finder.make_alias
.. autofunction:: macos.finder.new_window_folder
.. autofunction:: macos.finder.set_new_window_folder
.. autofunction:: macos.finder.quick_look
.. autofunction:: macos.finder.quit_menu
.. autofunction:: macos.finder.set_quit_menu
.. autofunction:: macos.finder.remove_icon
.. autofunction:: macos.finder.remove_old_trash_items
.. autofunction:: macos.finder.set_remove_old_trash_items
.. autofunction:: macos.finder.remove_tags
.. autofunction:: macos.finder.resolve_alias
.. autofunction:: macos.finder.restart
.. autofunction:: macos.finder.reveal
.. autofunction:: macos.finder.search_scope
.. autofunction:: macos.finder.set_search_scope
.. autofunction:: macos.finder.selection
.. autofunction:: macos.finder.show_desktop_icons
.. autofunction:: macos.finder.set_show_desktop_icons
.. autofunction:: macos.finder.set_show_drives_on_desktop
.. autofunction:: macos.finder.show_extensions
.. autofunction:: macos.finder.set_show_extensions
.. autofunction:: macos.finder.show_full_path_in_title
.. autofunction:: macos.finder.set_show_full_path_in_title
.. autofunction:: macos.finder.show_hidden_files
.. autofunction:: macos.finder.set_show_hidden_files
.. autofunction:: macos.finder.show_library_folder
.. autofunction:: macos.finder.set_show_library_folder
.. autofunction:: macos.finder.show_path_bar
.. autofunction:: macos.finder.set_show_path_bar
.. autofunction:: macos.finder.show_status_bar
.. autofunction:: macos.finder.set_show_status_bar
.. autofunction:: macos.finder.tags
.. autofunction:: macos.finder.set_tags
.. autofunction:: macos.finder.thumbnail
.. autofunction:: macos.finder.trash
.. autofunction:: macos.finder.wait_for_change
.. autofunction:: macos.finder.watch
```

## macos.hotkeys

```{eval-rst}
.. module:: macos.hotkeys

.. autofunction:: macos.hotkeys.has_permission
.. autoclass:: macos.hotkeys.Hotkey
   :members: unregister
.. autofunction:: macos.hotkeys.register
.. autofunction:: macos.hotkeys.request_permission
.. autofunction:: macos.hotkeys.run
.. autofunction:: macos.hotkeys.stop
.. autofunction:: macos.hotkeys.unregister
.. autofunction:: macos.hotkeys.wait
```

## macos.image

```{eval-rst}
.. module:: macos.image

.. autofunction:: macos.image.blur_background
.. autofunction:: macos.image.blur_faces
.. autofunction:: macos.image.contact_sheet
.. autofunction:: macos.image.convert
.. autofunction:: macos.image.crop
.. autofunction:: macos.image.dominant_colors
.. autofunction:: macos.image.effect
.. autofunction:: macos.image.enhance
.. autofunction:: macos.image.flip
.. autoclass:: macos.image.ImageInfo
.. autofunction:: macos.image.info
.. autofunction:: macos.image.location
.. autofunction:: macos.image.set_location
.. autofunction:: macos.image.metadata
.. autofunction:: macos.image.qr_code
.. autofunction:: macos.image.replace_background
.. autofunction:: macos.image.resize
.. autofunction:: macos.image.rotate
.. autofunction:: macos.image.straighten
.. autofunction:: macos.image.strip_metadata
.. autofunction:: macos.image.taken_at
.. autofunction:: macos.image.set_taken_at
.. autofunction:: macos.image.watermark
```

## macos.keyboard

```{eval-rst}
.. module:: macos.keyboard

.. autofunction:: macos.keyboard.set_app_shortcut
.. autofunction:: macos.keyboard.app_shortcuts
.. autofunction:: macos.keyboard.auto_brightness
.. autofunction:: macos.keyboard.set_auto_brightness
.. autofunction:: macos.keyboard.auto_capitalization
.. autofunction:: macos.keyboard.set_auto_capitalization
.. autofunction:: macos.keyboard.autocorrect
.. autofunction:: macos.keyboard.set_autocorrect
.. autofunction:: macos.keyboard.backlight_timeout
.. autofunction:: macos.keyboard.set_backlight_timeout
.. autofunction:: macos.keyboard.brightness
.. autofunction:: macos.keyboard.set_brightness
.. autofunction:: macos.keyboard.caps_lock
.. autofunction:: macos.keyboard.clear_remappings
.. autofunction:: macos.keyboard.double_space_period
.. autofunction:: macos.keyboard.set_double_space_period
.. autofunction:: macos.keyboard.fn_key_action
.. autofunction:: macos.keyboard.set_fn_key_action
.. autofunction:: macos.keyboard.full_keyboard_access
.. autofunction:: macos.keyboard.set_full_keyboard_access
.. autofunction:: macos.keyboard.has_permission
.. autofunction:: macos.keyboard.hold
.. autofunction:: macos.keyboard.inline_predictions
.. autofunction:: macos.keyboard.set_inline_predictions
.. autoclass:: macos.keyboard.KeyPress
.. autofunction:: macos.keyboard.key_repeat
.. autofunction:: macos.keyboard.set_key_repeat
.. autofunction:: macos.keyboard.layout
.. autofunction:: macos.keyboard.set_layout
.. autofunction:: macos.keyboard.layouts
.. autofunction:: macos.keyboard.press
.. autofunction:: macos.keyboard.press_and_hold
.. autofunction:: macos.keyboard.set_press_and_hold
.. autofunction:: macos.keyboard.remap
.. autofunction:: macos.keyboard.remappings
.. autofunction:: macos.keyboard.request_permission
.. autofunction:: macos.keyboard.smart_dashes
.. autofunction:: macos.keyboard.set_smart_dashes
.. autofunction:: macos.keyboard.smart_quotes
.. autofunction:: macos.keyboard.set_smart_quotes
.. autofunction:: macos.keyboard.standard_function_keys
.. autofunction:: macos.keyboard.set_standard_function_keys
.. autofunction:: macos.keyboard.set_system_shortcut
.. autodata:: macos.keyboard.SYSTEM_SHORTCUTS
.. autofunction:: macos.keyboard.system_shortcuts
.. autofunction:: macos.keyboard.type
.. autofunction:: macos.keyboard.watch
```

## macos.keychain

```{eval-rst}
.. module:: macos.keychain

.. autofunction:: macos.keychain.accounts
.. autofunction:: macos.keychain.delete
.. autofunction:: macos.keychain.get
.. autofunction:: macos.keychain.set
```

## macos.language

```{eval-rst}
.. module:: macos.language

.. autofunction:: macos.language.detect
.. autofunction:: macos.language.embedding
.. autofunction:: macos.language.entities
.. autoclass:: macos.language.Entity
.. autofunction:: macos.language.guess
.. autofunction:: macos.language.keywords
.. autofunction:: macos.language.sentiment
.. autofunction:: macos.language.similarity
```

## macos.maps

```{eval-rst}
.. module:: macos.maps

.. autofunction:: macos.maps.directions
.. autofunction:: macos.maps.geocode
.. autofunction:: macos.maps.open
.. autoclass:: macos.maps.Place
.. autofunction:: macos.maps.reverse_geocode
```

## macos.menubar

```{eval-rst}
.. module:: macos.menubar

.. autofunction:: macos.menubar.every
.. autoclass:: macos.menubar.Item
   :members: action, add, entries, remove, separator, set_icon, title, tooltip
.. autoclass:: macos.menubar.MenuItem
   :members: callback, checked, enabled, title
.. autofunction:: macos.menubar.quit
.. autofunction:: macos.menubar.run
.. autoclass:: macos.menubar.Timer
   :members: cancel
```

## macos.mouse

```{eval-rst}
.. module:: macos.mouse

.. autofunction:: macos.mouse.acceleration
.. autofunction:: macos.mouse.set_acceleration
.. autoclass:: macos.mouse.Click
.. autofunction:: macos.mouse.click
.. autofunction:: macos.mouse.click_text
.. autofunction:: macos.mouse.double_click_speed
.. autofunction:: macos.mouse.set_double_click_speed
.. autofunction:: macos.mouse.drag
.. autofunction:: macos.mouse.has_permission
.. autofunction:: macos.mouse.move
.. autofunction:: macos.mouse.position
.. autofunction:: macos.mouse.request_permission
.. autofunction:: macos.mouse.scroll
.. autofunction:: macos.mouse.scroll_speed
.. autofunction:: macos.mouse.set_scroll_speed
.. autofunction:: macos.mouse.tracking_speed
.. autofunction:: macos.mouse.set_tracking_speed
.. autofunction:: macos.mouse.watch
```

## macos.music

```{eval-rst}
.. module:: macos.music

.. autofunction:: macos.music.next
.. autofunction:: macos.music.now_playing
.. autofunction:: macos.music.pause
.. autofunction:: macos.music.play
.. autofunction:: macos.music.play_pause
.. autofunction:: macos.music.previous
.. autofunction:: macos.music.seek
.. autoclass:: macos.music.Track
.. autofunction:: macos.music.volume
.. autofunction:: macos.music.set_volume
```

## macos.network

```{eval-rst}
.. module:: macos.network

.. autoclass:: macos.network.Bandwidth
.. autofunction:: macos.network.bandwidth
.. autofunction:: macos.network.connect_vpn
.. autofunction:: macos.network.disconnect_vpn
.. autofunction:: macos.network.dns_servers
.. autofunction:: macos.network.interface
.. autofunction:: macos.network.interfaces
.. autofunction:: macos.network.ip
.. autofunction:: macos.network.is_online
.. autoclass:: macos.network.NetworkInterface
.. autoclass:: macos.network.Proxies
.. autofunction:: macos.network.proxies
.. autoclass:: macos.network.SpeedTest
.. autofunction:: macos.network.speed_test
.. autoclass:: macos.network.VPN
.. autofunction:: macos.network.vpns
.. autofunction:: macos.network.wifi_power
.. autofunction:: macos.network.set_wifi_power
.. autoclass:: macos.network.WiFiSignal
.. autofunction:: macos.network.wifi_signal
```

## macos.notifications

```{eval-rst}
.. module:: macos.notifications

.. autofunction:: macos.notifications.is_allowed
```

## macos.pdf

```{eval-rst}
.. module:: macos.pdf

.. autofunction:: macos.pdf.add_text
.. autoclass:: macos.pdf.Bookmark
.. autofunction:: macos.pdf.bookmarks
.. autofunction:: macos.pdf.set_bookmarks
.. autofunction:: macos.pdf.compress
.. autofunction:: macos.pdf.encrypt
.. autofunction:: macos.pdf.extract
.. autofunction:: macos.pdf.fill_form
.. autoclass:: macos.pdf.FormField
.. autofunction:: macos.pdf.form_fields
.. autofunction:: macos.pdf.from_images
.. autofunction:: macos.pdf.grayscale
.. autofunction:: macos.pdf.images
.. autofunction:: macos.pdf.merge
.. autoclass:: macos.pdf.Metadata
.. autofunction:: macos.pdf.metadata
.. autofunction:: macos.pdf.ocr
.. autofunction:: macos.pdf.page_count
.. autofunction:: macos.pdf.redact
.. autoclass:: macos.pdf.Redaction
.. autofunction:: macos.pdf.render
.. autofunction:: macos.pdf.rotate
.. autofunction:: macos.pdf.sign
.. autofunction:: macos.pdf.text
.. autofunction:: macos.pdf.watermark
```

## macos.power

```{eval-rst}
.. module:: macos.power

.. autoclass:: macos.power.Adapter
.. autofunction:: macos.power.adapter
.. autoclass:: macos.power.Battery
.. autofunction:: macos.power.battery
.. autofunction:: macos.power.keep_awake
.. autofunction:: macos.power.low_power_mode
.. autofunction:: macos.power.sleep
.. autoclass:: macos.power.SleepBlocker
.. autofunction:: macos.power.sleep_blockers
.. autofunction:: macos.power.sleep_display
```

## macos.printer

```{eval-rst}
.. module:: macos.printer

.. autofunction:: macos.printer.cancel
.. autofunction:: macos.printer.default
.. autofunction:: macos.printer.set_default
.. autofunction:: macos.printer.jobs
.. autoclass:: macos.printer.Printer
.. autofunction:: macos.printer.printers
.. autofunction:: macos.printer.print_file
.. autoclass:: macos.printer.PrintJob
```

## macos.schedule

```{eval-rst}
.. module:: macos.schedule

.. autofunction:: macos.schedule.add
.. autofunction:: macos.schedule.get
.. autoclass:: macos.schedule.Job
.. autofunction:: macos.schedule.jobs
.. autofunction:: macos.schedule.pause
.. autofunction:: macos.schedule.remove
.. autofunction:: macos.schedule.resume
.. autofunction:: macos.schedule.run_now
```

## macos.screen

```{eval-rst}
.. module:: macos.screen

.. autofunction:: macos.screen.brightness
.. autofunction:: macos.screen.set_brightness
.. autofunction:: macos.screen.color_at
.. autoclass:: macos.screen.Display
.. autoclass:: macos.screen.DisplayMode
.. autofunction:: macos.screen.display_mode
.. autofunction:: macos.screen.set_display_mode
.. autofunction:: macos.screen.display_modes
.. autofunction:: macos.screen.displays
.. autofunction:: macos.screen.find_text
.. autofunction:: macos.screen.has_permission
.. autofunction:: macos.screen.is_asleep
.. autofunction:: macos.screen.is_locked
.. autofunction:: macos.screen.lock
.. autofunction:: macos.screen.set_main_display
.. autofunction:: macos.screen.mirror
.. autofunction:: macos.screen.mirrored
.. autofunction:: macos.screen.night_shift
.. autofunction:: macos.screen.set_night_shift
.. autofunction:: macos.screen.night_shift_schedule
.. autofunction:: macos.screen.set_night_shift_schedule
.. autofunction:: macos.screen.night_shift_strength
.. autofunction:: macos.screen.set_night_shift_strength
.. autofunction:: macos.screen.record
.. autofunction:: macos.screen.request_permission
.. autofunction:: macos.screen.screensaver_delay
.. autofunction:: macos.screen.set_screensaver_delay
.. autofunction:: macos.screen.screenshot_folder
.. autofunction:: macos.screen.set_screenshot_folder
.. autofunction:: macos.screen.screenshot_format
.. autofunction:: macos.screen.set_screenshot_format
.. autofunction:: macos.screen.screenshot_name
.. autofunction:: macos.screen.set_screenshot_name
.. autofunction:: macos.screen.screenshot_shadow
.. autofunction:: macos.screen.set_screenshot_shadow
.. autofunction:: macos.screen.screenshot_target
.. autofunction:: macos.screen.set_screenshot_target
.. autofunction:: macos.screen.screenshot_thumbnail
.. autofunction:: macos.screen.set_screenshot_thumbnail
.. autofunction:: macos.screen.start_screensaver
.. autofunction:: macos.screen.stop_mirroring
.. autoclass:: macos.screen.TextMatch
   :members: center
.. autofunction:: macos.screen.true_tone
.. autofunction:: macos.screen.set_true_tone
.. autofunction:: macos.screen.wait_for_text
.. autofunction:: macos.screen.wallpaper
.. autofunction:: macos.screen.set_wallpaper
```

## macos.settings

```{eval-rst}
.. module:: macos.settings

.. autofunction:: macos.settings.apply
.. autofunction:: macos.settings.export
.. autofunction:: macos.settings.names
```

## macos.shortcuts

```{eval-rst}
.. module:: macos.shortcuts

.. autofunction:: macos.shortcuts.list
.. autofunction:: macos.shortcuts.run
```

## macos.sound

```{eval-rst}
.. module:: macos.sound

.. autofunction:: macos.sound.alert_sound
.. autofunction:: macos.sound.set_alert_sound
.. autofunction:: macos.sound.alert_volume
.. autofunction:: macos.sound.set_alert_volume
.. autofunction:: macos.sound.beep
.. autofunction:: macos.sound.names
.. autofunction:: macos.sound.play
.. autofunction:: macos.sound.ui_sounds
.. autofunction:: macos.sound.set_ui_sounds
```

## macos.speech

```{eval-rst}
.. module:: macos.speech

.. autoclass:: macos.speech.Voice
.. autofunction:: macos.speech.voices
```

## macos.spotlight

```{eval-rst}
.. module:: macos.spotlight

.. autofunction:: macos.spotlight.metadata
.. autofunction:: macos.spotlight.search
.. autofunction:: macos.spotlight.search_name
```

## macos.system

```{eval-rst}
.. module:: macos.system

.. autofunction:: macos.system.available_updates
.. autofunction:: macos.system.battery_percentage_shown
.. autofunction:: macos.system.build
.. autofunction:: macos.system.camera_in_use
.. autofunction:: macos.system.clock_format
.. autofunction:: macos.system.set_clock_format
.. autofunction:: macos.system.computer_name
.. autoclass:: macos.system.Connection
.. autofunction:: macos.system.connections
.. autofunction:: macos.system.cpu_usage
.. autoclass:: macos.system.CrashReport
.. autofunction:: macos.system.crash_reports
.. autoclass:: macos.system.DiskHealth
.. autofunction:: macos.system.disk_health
.. autofunction:: macos.system.ds_store_on_network
.. autofunction:: macos.system.set_ds_store_on_network
.. autofunction:: macos.system.ds_store_on_usb
.. autofunction:: macos.system.set_ds_store_on_usb
.. autofunction:: macos.system.eject
.. autoclass:: macos.system.EnergyUsage
.. autofunction:: macos.system.energy_usage
.. autofunction:: macos.system.expanded_save_dialog
.. autofunction:: macos.system.set_expanded_save_dialog
.. autofunction:: macos.system.fonts
.. autoclass:: macos.system.GPUUsage
.. autofunction:: macos.system.gpu_usage
.. autofunction:: macos.system.idle_time
.. autofunction:: macos.system.keep_windows_on_quit
.. autofunction:: macos.system.set_keep_windows_on_quit
.. autofunction:: macos.system.kill
.. autofunction:: macos.system.lid_closed
.. autoclass:: macos.system.LogEntry
.. autofunction:: macos.system.logs
.. autofunction:: macos.system.measurement_units
.. autofunction:: macos.system.set_measurement_units
.. autofunction:: macos.system.memory
.. autoclass:: macos.system.MemoryUsage
   :members: free, percent
.. autofunction:: macos.system.memory_usage
.. autodata:: macos.system.MENU_BAR_ITEMS
.. autofunction:: macos.system.menu_bar_items
.. autofunction:: macos.system.set_menu_bar_items
.. autofunction:: macos.system.menu_bar_spacing
.. autofunction:: macos.system.set_menu_bar_spacing
.. autofunction:: macos.system.microphone_in_use
.. autofunction:: macos.system.model
.. autofunction:: macos.system.model_identifier
.. autofunction:: macos.system.mount_image
.. autoclass:: macos.system.NetworkUsage
.. autofunction:: macos.system.network_usage
.. autofunction:: macos.system.open_files
.. autofunction:: macos.system.open_photos_on_device_connect
.. autofunction:: macos.system.set_open_photos_on_device_connect
.. autoclass:: macos.system.Port
.. autofunction:: macos.system.port_owner
.. autofunction:: macos.system.ports
.. autoclass:: macos.system.Process
.. autofunction:: macos.system.process
.. autofunction:: macos.system.processes
.. autofunction:: macos.system.processor
.. autofunction:: macos.system.save_to_icloud_by_default
.. autofunction:: macos.system.set_save_to_icloud_by_default
.. autoclass:: macos.system.SecurityStatus
.. autofunction:: macos.system.security_status
.. autofunction:: macos.system.set_show_battery_percentage
.. autoclass:: macos.system.StartupItem
.. autofunction:: macos.system.startup_items
.. autofunction:: macos.system.temperature_unit
.. autofunction:: macos.system.set_temperature_unit
.. autofunction:: macos.system.thermal_state
.. autofunction:: macos.system.unmount_image
.. autoclass:: macos.system.Update
.. autofunction:: macos.system.uptime
.. autoclass:: macos.system.USBDevice
.. autofunction:: macos.system.usb_devices
.. autofunction:: macos.system.version
.. autoclass:: macos.system.Volume
.. autofunction:: macos.system.volumes
.. autofunction:: macos.system.wait_for_activity
.. autofunction:: macos.system.wait_for_idle
.. autofunction:: macos.system.who_uses
```

## macos.time_machine

```{eval-rst}
.. module:: macos.time_machine

.. autofunction:: macos.time_machine.backup_now
.. autofunction:: macos.time_machine.destinations
.. autofunction:: macos.time_machine.exclude
.. autofunction:: macos.time_machine.include
.. autofunction:: macos.time_machine.is_backing_up
.. autofunction:: macos.time_machine.is_excluded
.. autofunction:: macos.time_machine.last_backup
.. autofunction:: macos.time_machine.progress
.. autofunction:: macos.time_machine.stop_backup
```

## macos.trackpad

```{eval-rst}
.. module:: macos.trackpad

.. autofunction:: macos.trackpad.click_pressure
.. autofunction:: macos.trackpad.set_click_pressure
.. autofunction:: macos.trackpad.set_gesture
.. autodata:: macos.trackpad.GESTURES
.. autofunction:: macos.trackpad.gestures
.. autofunction:: macos.trackpad.natural_scrolling
.. autofunction:: macos.trackpad.set_natural_scrolling
.. autofunction:: macos.trackpad.secondary_click
.. autofunction:: macos.trackpad.set_secondary_click
.. autofunction:: macos.trackpad.tap_to_click
.. autofunction:: macos.trackpad.set_tap_to_click
.. autofunction:: macos.trackpad.three_finger_drag
.. autofunction:: macos.trackpad.set_three_finger_drag
.. autofunction:: macos.trackpad.tracking_speed
.. autofunction:: macos.trackpad.set_tracking_speed
```

## macos.video

```{eval-rst}
.. module:: macos.video

.. autofunction:: macos.video.add_audio
.. autofunction:: macos.video.add_language_track
.. autofunction:: macos.video.concat
.. autofunction:: macos.video.convert
.. autofunction:: macos.video.crop
.. autofunction:: macos.video.frame
.. autofunction:: macos.video.frames
.. autofunction:: macos.video.from_images
.. autofunction:: macos.video.info
.. autofunction:: macos.video.mute
.. autofunction:: macos.video.reverse
.. autofunction:: macos.video.rotate
.. autofunction:: macos.video.speed
.. autofunction:: macos.video.to_gif
.. autofunction:: macos.video.trim
.. autoclass:: macos.video.VideoInfo
```

## macos.vision

```{eval-rst}
.. module:: macos.vision

.. autoclass:: macos.vision.Aesthetics
.. autofunction:: macos.vision.aesthetics
.. autoclass:: macos.vision.Animal
.. autofunction:: macos.vision.animals
.. autoclass:: macos.vision.Barcode
.. autofunction:: macos.vision.barcodes
.. autofunction:: macos.vision.best_shot
.. autofunction:: macos.vision.body_pose
.. autofunction:: macos.vision.classify
.. autofunction:: macos.vision.duplicates
.. autofunction:: macos.vision.faces
.. autoclass:: macos.vision.Hand
.. autofunction:: macos.vision.hand_pose
.. autofunction:: macos.vision.horizon
.. autofunction:: macos.vision.image_distance
.. autofunction:: macos.vision.languages
.. autofunction:: macos.vision.lines
.. autoclass:: macos.vision.Pose
.. autofunction:: macos.vision.remove_background
.. autofunction:: macos.vision.scan_document
.. autofunction:: macos.vision.smart_crop
.. autofunction:: macos.vision.text
.. autoclass:: macos.vision.TextLine
```

## macos.volume

```{eval-rst}
.. module:: macos.volume

.. autofunction:: macos.volume.get
.. autofunction:: macos.volume.is_muted
.. autofunction:: macos.volume.mute
.. autofunction:: macos.volume.set
.. autofunction:: macos.volume.unmute
```

## macos.windows

```{eval-rst}
.. module:: macos.windows

.. autofunction:: macos.windows.animations
.. autofunction:: macos.windows.set_animations
.. autofunction:: macos.windows.click_wallpaper_to_show_desktop
.. autofunction:: macos.windows.set_click_wallpaper_to_show_desktop
.. autofunction:: macos.windows.double_click_title_bar
.. autofunction:: macos.windows.set_double_click_title_bar
.. autofunction:: macos.windows.focused
.. autofunction:: macos.windows.has_permission
.. autodata:: macos.windows.LAYOUTS
   :no-value:
.. autofunction:: macos.windows.list
.. autofunction:: macos.windows.request_permission
.. autofunction:: macos.windows.tile
.. autofunction:: macos.windows.tile_all
.. autofunction:: macos.windows.tiling
.. autofunction:: macos.windows.set_tiling
.. autofunction:: macos.windows.wait_for
.. autoclass:: macos.windows.Window
   :members: title, position, size, frame, minimized, fullscreen, move, resize, set_frame, center, focus, minimize, restore, close, set_fullscreen, screenshot, snap
```

## Exceptions

```{eval-rst}
.. autoexception:: macos.MacOSError
.. autoexception:: macos.NotSupportedError
.. autoexception:: macos.PermissionDeniedError
.. autoexception:: macos.AppNotFoundError
.. autoexception:: macos.ShortcutNotFoundError
.. autoexception:: macos.KeychainError
.. autoexception:: macos.CommandError
```
