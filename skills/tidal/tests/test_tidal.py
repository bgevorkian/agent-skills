from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import sys

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

from tidal import (  # noqa: E402
    album_to_json,
    artist_to_json,
    env_write_enabled,
    jsonable,
    me_to_json,
    parse_indices,
    parse_reference,
    require_write_enabled,
    session_file_path,
    track_to_json,
    playlist_to_json,
    user_data_dir,
)


def expect_rejected(func, *args, **kwargs) -> None:
    try:
        func(*args, **kwargs)
    except ValueError:
        return
    raise AssertionError(f"expected ValueError: {func.__name__}{args!r}{kwargs!r}")


def main() -> None:
    ref = parse_reference("https://tidal.com/browse/playlist/123e4567-e89b-12d3-a456-426614174000")
    assert ref["kind"] == "playlist"
    assert ref["id"] == "123e4567-e89b-12d3-a456-426614174000"

    ref = parse_reference("track:42")
    assert ref["kind"] == "track"
    assert ref["id"] == "42"

    ref = parse_reference("42", "track")
    assert ref["kind"] == "track"
    assert ref["id"] == "42"

    ref = parse_reference("mix-list-001")
    assert ref["kind"] == "playlist"

    expect_rejected(parse_reference, "42")
    expect_rejected(parse_reference, "https://example.com/track/42")
    expect_rejected(parse_reference, "album:42", "track")

    assert parse_indices(["3,1", "1", "0"]) == [0, 1, 3]
    expect_rejected(parse_indices, ["-1"])

    linux_dir = user_data_dir(env={}, home=Path("/home/tester"), platform="linux")
    assert linux_dir == Path("/home/tester/.local/share/agent-skills/tidal")

    xdg_dir = user_data_dir(env={"XDG_DATA_HOME": "/data"}, home=Path("/home/tester"), platform="linux")
    assert xdg_dir == Path("/data/agent-skills/tidal")

    win_dir = user_data_dir(env={"APPDATA": "C:/Data/Roaming"}, home=Path("C:/Users/tester"), platform="win32")
    assert win_dir == Path("C:/Data/Roaming/agent-skills/tidal")

    assert session_file_path(env={"TIDAL_SESSION_FILE": "~/custom/tidal.json"}, home=Path("/home/tester"), platform="linux") == Path("~/custom/tidal.json").expanduser()
    assert session_file_path(env={}, home=Path("/home/tester"), platform="linux") == Path("/home/tester/.local/share/agent-skills/tidal/session.json")

    assert env_write_enabled({"TIDAL_ALLOW_WRITE": "true"}) is True
    assert env_write_enabled({"TIDAL_ALLOW_WRITE": "TRUE"}) is True
    assert env_write_enabled({"TIDAL_ALLOW_WRITE": "1"}) is False
    expect_rejected(require_write_enabled, False, {"TIDAL_ALLOW_WRITE": "true"})
    expect_rejected(require_write_enabled, True, {"TIDAL_ALLOW_WRITE": "false"})
    require_write_enabled(True, {"TIDAL_ALLOW_WRITE": "true"})

    track = SimpleNamespace(
        id=101,
        name="Трек",
        artist=SimpleNamespace(name="Исполнитель"),
        album=SimpleNamespace(name="Альбом"),
        duration=180,
        version=None,
        explicit=False,
        popularity=77,
        isrc="ISRC123",
    )
    track_payload = track_to_json(track)
    assert track_payload["title"] == "Трек"
    assert track_payload["artist"] == "Исполнитель"
    assert track_payload["album"] == "Альбом"
    assert track_payload["url"].endswith("/track/101")

    album = SimpleNamespace(
        id=202,
        title="Album",
        artist=SimpleNamespace(name="Artist"),
        num_tracks=9,
        num_volumes=1,
        release_date=date(2024, 1, 2),
        explicit=True,
    )
    assert album_to_json(album)["release_date"] == "2024-01-02"

    artist = SimpleNamespace(id=303, name="Artist", popularity=55)
    assert artist_to_json(artist)["url"].endswith("/artist/303")

    playlist = SimpleNamespace(
        id="pl-1",
        name="My List",
        description="Desc",
        num_tracks=5,
        public=True,
        creator=SimpleNamespace(name="tester"),
    )
    playlist_payload = playlist_to_json(playlist)
    assert playlist_payload["title"] == "My List"
    assert playlist_payload["creator"] == "tester"

    me = SimpleNamespace(id=1, username="tester", email="a@example.com", first_name="A", last_name="B")
    assert me_to_json(me)["username"] == "tester"

    assert jsonable(Decimal("1.20")) == "1.20"
    assert jsonable(b"\x00\xff") == "00ff"
    print("tidal tests: OK")


if __name__ == "__main__":
    main()
