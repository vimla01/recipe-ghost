from haath.models import Segment, Word
from haath.transcribe import split_long_segments


def seg_from(words: list[tuple[float, str]], start_id: int = 0) -> Segment:
    ws = [Word(start=t, end=t + 0.4, word=w) for t, w in words]
    return Segment(id=start_id, start=ws[0].start, end=ws[-1].end, text="".join(w.word for w in ws).strip(), words=ws)


def test_long_segment_is_cut_at_sentence_ends_with_word_times():
    seg = seg_from([
        (0.0, " अब"), (0.5, " घी"), (1.0, " डालो,"), (1.5, " खूब"), (2.0, " सारा"), (2.5, " घी।"),
        (6.0, " फिर"), (6.5, " थोड़ा"), (7.0, " पानी"), (7.5, " डालो।"),
        (11.0, " Dhakkan"), (11.5, " mat"), (12.0, " kholna!"),
    ])
    out = split_long_segments([seg], max_sec=8)
    assert [s.start for s in out] == [0.0, 6.0, 11.0]
    assert out[0].text == "अब घी डालो, खूब सारा घी।"
    assert out[2].text == "Dhakkan mat kholna!"
    assert [s.id for s in out] == [0, 1, 2]


def test_falls_back_to_commas_and_glues_tiny_pieces():
    seg = seg_from([(i * 1.0, w) for i, w in enumerate(
        [" मुठी", " में", " दबाओ", " तो", " लड्डू", " जैसा", " बंध", " जाए,", " बस", " इतना,",
         " फिर", " पानी", " डाल", " के", " सख्त", " आटा"])])
    out = split_long_segments([seg], max_sec=8)
    assert out[0].text.endswith("बस इतना,")  # 2-word fragment glued, not its own line
    assert out[1].start == 10.0


def test_short_segments_untouched():
    seg = seg_from([(0.0, " haldi"), (0.5, " daalo.")])
    assert split_long_segments([seg]) == [seg]


def test_unpunctuated_speech_is_cut_at_pauses():
    # Whisper often writes Hindi with no punctuation; the longest silences mark the thoughts.
    words = [(0.0, " पोहा"), (0.4, " कैसे"), (0.8, " बनता"), (1.2, " है"), (1.6, " दिखाता"), (2.0, " हूँ"),
             (4.5, " पानी"), (4.9, " से"), (5.3, " धो"), (5.7, " लीजिए"),
             (9.0, " फिर"), (9.4, " तेल"), (9.8, " गरम"), (10.2, " कीजिए")]
    out = split_long_segments([seg_from(words)], max_sec=5)
    assert [s.start for s in out] == [0.0, 4.5, 9.0]
    assert out[0].text == "पोहा कैसे बनता है दिखाता हूँ"
