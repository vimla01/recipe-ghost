from haath.llm import chunk_segments, merge_recipes, write_recipe
from haath.models import Ingredient, Recipe, Segment, Step, Transcript


def long_segments(n: int = 400) -> list[Segment]:
    return [Segment(id=i, start=i * 5.0, end=i * 5.0 + 5, text=f"वाक्य संख्या {i} में मसाला भूनते रहो जब तक खुशबू न आए") for i in range(n)]


def test_short_transcript_is_one_chunk():
    segs = long_segments(10)
    assert chunk_segments(segs, 16384) == [segs]


def test_long_transcript_chunks_cover_everything_with_overlap():
    segs = long_segments()
    chunks = chunk_segments(segs, 8192, overlap=2)
    assert len(chunks) > 1
    seen = {s.id for c in chunks for s in c}
    assert seen == {s.id for s in segs}
    for a, b in zip(chunks, chunks[1:]):
        assert [s.id for s in a[-2:]] == [s.id for s in b[:2]]  # seam overlap


def test_merge_dedupes_and_prefers_better_info():
    a = Recipe(
        dish="Dal Baati",
        ingredients=[Ingredient(name="Turmeric (haldi)", her_words="", approx="~1/2 tsp", confidence="low")],
        steps=[Step(text="Knead the dough", her_cue="naram aata", start_sec=10), Step(text="Make balls of dough", start_sec=50)],
        quotes=["Pyaar se goondho"],
        tips=["Use desi ghee"],
    )
    b = Recipe(
        story="Nanaji loved it",
        ingredients=[
            Ingredient(name="Turmeric", her_words="thoda sa haldi", approx="~1 tsp", confidence="med"),
            Ingredient(name="Ghee", her_words="khoob saara ghee", approx="~4 tbsp", confidence="low"),
        ],
        steps=[Step(text="Make balls of the dough", start_sec=52), Step(text="Bake the baati", her_cue="sunehri hone tak", start_sec=120)],
        quotes=["Pyaar se goondho!", "Baati ko jaldi mat karna"],
        tips=["use desi ghee"],
    )
    m = merge_recipes([a, b])
    assert m.dish == "Dal Baati" and m.story == "Nanaji loved it"
    assert [i.name for i in m.ingredients] == ["Turmeric (haldi)", "Ghee"]
    assert m.ingredients[0].her_words == "thoda sa haldi"
    assert (m.ingredients[0].approx, m.ingredients[0].confidence) == ("~1 tsp", "med")
    assert [s.text for s in m.steps] == ["Knead the dough", "Make balls of dough", "Bake the baati"]
    assert len(m.quotes) == 2 and len(m.tips) == 1


def test_write_recipe_chunks_and_merges_with_fake_model():
    t = Transcript(language="hi", duration=2000, segments=long_segments())
    calls = []

    def fake_ask(messages):
        calls.append(messages)
        n = len(calls)
        text = ["Knead the dough", "Bake the baati", "Make the tadka", "Serve with ghee"][(n - 1) % 4]
        return Recipe(dish="ignored", steps=[Step(text=text, start_sec=n * 100)]).model_dump_json()

    r = write_recipe(t, cook="Nani", dish="Dal", model="x", host="", num_ctx=8192, ask=fake_ask)
    assert len(calls) > 1
    assert "PART 1 of" in calls[0][0]["content"]
    assert r.dish == "Dal" and r.cook == "Nani"
    assert len(r.steps) == len(calls)


def test_copied_prompt_examples_are_filtered():
    from haath.llm import EXAMPLE_QUESTIONS, SYSTEM_PROMPT

    assert EXAMPLE_QUESTIONS[0] in SYSTEM_PROMPT and "{examples}" not in SYSTEM_PROMPT
    t = Transcript(language="hi", duration=10, segments=long_segments(2))
    reply = Recipe(ask_next_time=[EXAMPLE_QUESTIONS[0].lower(), "How many baatis does this make?"]).model_dump_json()
    r = write_recipe(t, "", "", "x", "", 16384, ask=lambda m: reply)
    assert r.ask_next_time == ["How many baatis does this make?"]
