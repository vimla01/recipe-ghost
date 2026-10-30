from haath.models import Recipe, Step
from haath.verify import TranscriptIndex, snap_step_time, verify_recipe


def test_snaps_to_segment_containing_cue(hindi_transcript):
    idx = TranscriptIndex(hindi_transcript)
    # Gemma guessed 3.0, but the cue is in the segment starting at 22.0
    sec, ok = snap_step_time(idx, "Fry until the oil separates", "jab tak tel chhod de", 3.0)
    assert (sec, ok) == (22.0, True)


def test_repeated_cue_picks_occurrence_nearest_to_guess(hindi_transcript):
    idx = TranscriptIndex(hindi_transcript)
    assert snap_step_time(idx, "Add turmeric", "थोड़ा सा हल्दी", 15.0)[0] == 14.2
    assert snap_step_time(idx, "Add turmeric to dal", "थोड़ा सा हल्दी", 40.0)[0] == 38.5


def test_snaps_by_step_words_when_no_cue(hindi_transcript):
    idx = TranscriptIndex(hindi_transcript)
    sec, ok = snap_step_time(idx, "dhakkan mat kholna — keep the lid closed", "", 0.0)
    assert (sec, ok) == (31.0, True)


def test_fallback_to_segment_around_guess(hindi_transcript):
    idx = TranscriptIndex(hindi_transcript)
    sec, ok = snap_step_time(idx, "Serve hot", "", 16.9)
    assert (sec, ok) == (14.2, False)


def test_verify_clamps_and_reports_unsnapped(hindi_transcript):
    r = Recipe(steps=[Step(text="Serve hot", start_sec=999), Step(text="Fry", her_cue="tel chhod de", start_sec=5)])
    out, rep = verify_recipe(r, hindi_transcript)
    assert out.steps[0].start_sec == 38.5  # nearest real segment, never past the audio
    assert out.steps[1].start_sec == 22.0
    assert rep.unsnapped_steps == [0]
