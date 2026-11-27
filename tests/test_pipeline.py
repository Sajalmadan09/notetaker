import numpy as np

from notetaker.pipeline import transcribe_meeting


class NoLidAsr:  # like TorchAsr: transcribes, cannot identify languages
    def transcribe(self, wav, lang, mode="native"):
        return f"{lang}:{mode}"


class Lid:
    def identify(self, wav):
        return [("bn", 0.9)]


class OneTurn:
    def process(self, audio, n):
        return [(0.0, 1.0, 0)]


def test_auto_language_uses_lid_engine_not_transcriber():
    doc = transcribe_meeting((0.1 * np.sin(np.arange(32000) / 5)).astype(np.float32), lang="auto", mode="mixed",
                             asr=NoLidAsr(), diarizer=OneTurn(), lid=Lid())
    assert doc["lang"] == "bn" and doc["turns"][0]["text"] == "bn:mixed"


class TwoTrackDiarizer:
    def process(self, audio, n):
        return [(0.0, 1.0, 0)] if n == 1 else [(1.0, 2.0, 0), (2.0, 3.0, 1)]


class EchoAsr:  # the mic "hears" the other person too, i.e. speakers without headphones
    def transcribe(self, wav, lang, mode="native"):
        return "same words here" if abs(float(wav.mean())) < 0.05 else f"turn {wav.mean():.1f}"


def test_two_tracks_label_you_and_merge_in_time_order():
    import numpy as np
    from notetaker.pipeline import transcribe_two_tracks
    tone = (0.1 * np.sin(np.arange(48000) / 5)).astype(np.float32)
    doc = transcribe_two_tracks(tone, tone, lang="hi", asr=NoLidAsr(), diarizer=TwoTrackDiarizer(), lid=Lid())
    assert [(t["speaker"], t["track"]) for t in doc["turns"]] == [(0, "mic"), (1, "others"), (2, "others")]


def test_silent_track_is_skipped_and_echo_dropped():
    import numpy as np
    from notetaker.pipeline import _drop_echo, transcribe_two_tracks
    tone = (0.1 * np.sin(np.arange(48000) / 5)).astype(np.float32)
    doc = transcribe_two_tracks(tone, np.zeros(48000, np.float32), asr=NoLidAsr(), diarizer=TwoTrackDiarizer(), lid=Lid())
    assert [t["track"] for t in doc["turns"]] == ["mic"]  # nobody else spoke
    turns = [{"start": 1.0, "end": 2.0, "speaker": 0, "text": "Same words here", "track": "mic"},
             {"start": 1.1, "end": 2.0, "speaker": 1, "text": "same words here.", "track": "others"},
             {"start": 3.0, "end": 4.0, "speaker": 0, "text": "my own point", "track": "mic"}]
    assert [t["text"] for t in _drop_echo(turns)] == ["same words here.", "my own point"]
