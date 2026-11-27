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
    doc = transcribe_meeting(np.zeros(32000, np.float32), lang="auto", mode="mixed",
                             asr=NoLidAsr(), diarizer=OneTurn(), lid=Lid())
    assert doc["lang"] == "bn" and doc["turns"][0]["text"] == "bn:mixed"
