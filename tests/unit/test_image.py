"""Unit tests for :mod:`macos.image`. They run on any platform."""

import sys
from datetime import datetime, timedelta, timezone

import pytest

import macos


@pytest.mark.parametrize("name", ["out.webp", "out.avif", "out.txt"])
def test_image_rejects_formats_it_cannot_write(name, tmp_path):
    with pytest.raises(ValueError, match="can't write"):
        macos.image.convert(__file__, tmp_path / name)


def test_dominant_colors_clusters_by_share():
    colors = [(250, 250, 250)] * 60 + [(252, 248, 251)] * 10 + [(20, 30, 200)] * 25 + [(200, 20, 20)] * 5

    clusters = macos.image._kmeans(colors, 5)

    # Near-identical whites share a cluster; the result is sorted by size.
    assert [size for _, size in clusters] == [70, 25, 5]
    assert [tuple(round(channel) for channel in color) for color, _ in clusters[1:]] == [(20, 30, 200), (200, 20, 20)]
    assert macos.image._kmeans(colors, 1)[0][1] == 100
    assert macos.image._kmeans([], 3) == []


def test_taken_at_reads_the_time_zone_when_recorded(monkeypatch):
    exif = {"DateTimeOriginal": "2024:05:01 10:30:00", "OffsetTimeOriginal": "-03:00"}
    monkeypatch.setattr(macos.image, "metadata", lambda path: {"{Exif}": exif})

    assert macos.image.taken_at("photo.jpg") == datetime(2024, 5, 1, 10, 30, tzinfo=timezone(timedelta(hours=-3)))

    exif["OffsetTimeOriginal"] = "bogus"
    assert macos.image.taken_at("photo.jpg") == datetime(2024, 5, 1, 10, 30)


@pytest.mark.parametrize("offset", ["+01:99", "x01:00", "+01x00", "+24:00", "+01:-1", "+aa:00"])
def test_taken_at_ignores_invalid_offsets(monkeypatch, offset):
    exif = {"DateTimeOriginal": "2024:05:01 10:30:00", "OffsetTimeOriginal": offset}
    monkeypatch.setattr(macos.image, "metadata", lambda path: {"{Exif}": exif})
    assert macos.image.taken_at("photo.jpg") == datetime(2024, 5, 1, 10, 30)


@pytest.mark.parametrize("offset, minutes", [("+05:30", 330), ("-03:45", -225), ("+00:00", 0), ("-00:00", 0), ("+23:59", 1439)])
def test_taken_at_preserves_valid_offsets(monkeypatch, offset, minutes):
    exif = {"DateTimeOriginal": "2024:05:01 10:30:00", "OffsetTimeOriginal": offset}
    monkeypatch.setattr(macos.image, "metadata", lambda path: {"{Exif}": exif})
    assert macos.image.taken_at("photo.jpg") == datetime(2024, 5, 1, 10, 30, tzinfo=timezone(timedelta(minutes=minutes)))


def test_set_taken_at_writes_the_offset(monkeypatch):
    written = []
    monkeypatch.setattr(macos.image, "_set_properties", lambda path, changes, output: written.append(changes))

    macos.image.set_taken_at("a.jpg", datetime(2024, 5, 1, 10, 30, tzinfo=timezone(timedelta(hours=5, minutes=30))))
    macos.image.set_taken_at("a.jpg", datetime(2024, 5, 1, 10, 30))
    macos.image.set_location("a.jpg", -22.95, 43.21)

    assert written[0]["{Exif}"] == {
        "DateTimeOriginal": "2024:05:01 10:30:00",
        "DateTimeDigitized": "2024:05:01 10:30:00",
        "OffsetTimeOriginal": "+05:30",
        "OffsetTimeDigitized": "+05:30",
    }
    assert "OffsetTimeOriginal" not in written[1]["{Exif}"]
    assert written[2] == {"{GPS}": {"Latitude": 22.95, "LatitudeRef": "S", "Longitude": 43.21, "LongitudeRef": "E"}}


def test_image_argument_checks(tmp_path):
    with pytest.raises(ValueError, match="needs a width"):
        macos.image.resize(__file__, tmp_path / "out.png")
    with pytest.raises(ValueError, match="positive"):
        macos.image.resize(__file__, tmp_path / "out.png", width=0)
    with pytest.raises(ValueError, match="quality"):
        macos.image.convert(__file__, tmp_path / "out.jpg", quality=2)
    with pytest.raises(ValueError, match="correction"):
        macos.image.qr_code("x", correction="Z")
    with pytest.raises(ValueError, match="size"):
        macos.image.qr_code("x", size=0)
    with pytest.raises(ValueError, match="multiple of 90"):
        macos.image.rotate(__file__, tmp_path / "out.png", 45)
    with pytest.raises(ValueError, match="direction"):
        macos.image.flip(__file__, tmp_path / "out.png", direction="diagonal")
    with pytest.raises(ValueError, match="positive"):
        macos.image.crop(__file__, tmp_path / "out.png", (0, 0, 0, 10))
    with pytest.raises(ValueError, match="latitude"):
        macos.image.set_location(__file__, 91, 0)
    with pytest.raises(ValueError, match="longitude"):
        macos.image.set_location(__file__, 0, -181)
    with pytest.raises(ValueError, match="count"):
        macos.image.dominant_colors(__file__, count=0)
    with pytest.raises(ValueError, match="name must be one of"):
        macos.image.effect(__file__, tmp_path / "out.png", "sepia")
    with pytest.raises(ValueError, match="strength"):
        macos.image.blur_background(__file__, tmp_path / "out.png", strength=0)
    with pytest.raises(ValueError, match="empty"):
        macos.image.watermark(__file__, tmp_path / "out.png", " ")
    with pytest.raises(ValueError, match="opacity"):
        macos.image.watermark(__file__, tmp_path / "out.png", "x", opacity=0)
    with pytest.raises(ValueError, match="hex color"):
        macos.image.watermark(__file__, tmp_path / "out.png", "x", color="white")
    with pytest.raises(ValueError, match="at least one"):
        macos.image.contact_sheet([], tmp_path / "out.png")
    with pytest.raises(ValueError, match="positive"):
        macos.image.contact_sheet([__file__], tmp_path / "out.png", columns=0)


@pytest.mark.skipif(sys.platform != "darwin", reason="writes images with ImageIO")
def test_a_metadata_copy_takes_the_format_of_its_extension(tmp_path):
    from tests.helpers import rgb_png

    picture = tmp_path / "picture.png"
    picture.write_bytes(rgb_png(40, 30, lambda x, y: (200, 30, 30)))
    photo = macos.image.convert(picture, tmp_path / "photo.jpg")
    when = datetime(2024, 5, 1, 10, 30)

    as_png = macos.image.set_taken_at(photo, when, output=tmp_path / "copy.png")
    assert as_png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n" and macos.image.info(as_png).format == "png"
    assert macos.image.taken_at(as_png) == when
    same = macos.image.set_location(photo, -22.95, -43.21, output=tmp_path / "copy.jpeg")
    assert macos.image.info(same).format == "jpeg" and macos.image.location(same) == pytest.approx((-22.95, -43.21))
    with pytest.raises(ValueError, match="can't write '.webp' images"):
        macos.image.set_taken_at(photo, when, output=tmp_path / "copy.webp")
    assert not (tmp_path / "copy.webp").exists()
    # In place, the image keeps its own format, whatever its name says.
    misnamed = tmp_path / "really-a-jpeg.png"
    misnamed.write_bytes(photo.read_bytes())
    macos.image.set_taken_at(misnamed, when)
    assert misnamed.read_bytes()[:2] == b"\xff\xd8" and macos.image.taken_at(misnamed) == when


@pytest.mark.skipif(sys.platform != "darwin", reason="writes images with ImageIO")
def test_written_images_get_the_usual_permissions(tmp_path):
    import os
    import stat

    from tests.helpers import rgb_png

    old = os.umask(0o022)
    try:
        picture = tmp_path / "picture.png"
        picture.write_bytes(rgb_png(40, 30, lambda x, y: (200, 30, 30)))
        photo = macos.image.convert(picture, tmp_path / "new" / "photo.jpg")
        assert stat.S_IMODE(photo.stat().st_mode) == 0o644
        os.chmod(str(photo), 0o660)
        macos.image.set_taken_at(photo, datetime(2024, 5, 1, 10, 30))
        macos.image.rotate(photo, photo, 90)
        assert stat.S_IMODE(photo.stat().st_mode) == 0o660
        assert os.listdir(str(photo.parent)) == ["photo.jpg"]
    finally:
        os.umask(old)
