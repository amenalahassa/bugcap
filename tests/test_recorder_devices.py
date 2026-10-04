import pytest

from bugcap import recorder

SAMPLE = """\
[AVFoundation indev @ 0x7f8] AVFoundation video devices:
[AVFoundation indev @ 0x7f8] [0] FaceTime HD Camera
[AVFoundation indev @ 0x7f8] [1] Capture screen 0
[AVFoundation indev @ 0x7f8] [2] Capture screen 1
[AVFoundation indev @ 0x7f8] AVFoundation audio devices:
[AVFoundation indev @ 0x7f8] [0] MacBook Pro Microphone
"""


def test_screen_index_found():
    assert recorder.parse_avfoundation_screen_index(SAMPLE) == 1


def test_missing_screen_entry_gives_guidance():
    with pytest.raises(recorder.RecorderError) as exc:
        recorder.parse_avfoundation_screen_index("[0] FaceTime HD Camera")
    assert "Screen Recording" in exc.value.guidance
