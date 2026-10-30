from haath.models import Ingredient, Recipe, Step
from haath.verify import TranscriptIndex, normalize, verify_recipe


# ---- normalization ------------------------------------------------------------


def test_normalize_hinglish_case_punctuation_whitespace():
    assert normalize("  Thoda   sa HALDI!! ") == "thoda sa haldi"
    assert normalize("jab tak tel chhod de...") == normalize("Jab-tak, tel  chhod de")


def test_normalize_devanagari_keeps_matras_drops_danda():
    s = "थोड़ा सा हल्दी।"
    n = normalize(s)
    assert "।" not in n
    assert "ड़" in n or "ड़" in n  # nukta survives
    assert "्" in n  # virama in हल्दी survives (combining mark, not punctuation)


def test_normalize_unifies_nukta_forms_and_zero_width():
    composed = "\u095c"  # ड़ precomposed
    decomposed = "\u0921\u093c"  # ड + nukta
    assert composed != decomposed
    assert normalize("थो" + composed + "ा") == normalize("थो" + decomposed + "ा")
    assert normalize("हल्‍दी") == normalize("हल्दी")  # ZWJ dropped


# ---- verification -------------------------------------------------------------


def test_real_quotes_kept_invented_dropped(hindi_transcript):
    r = Recipe(
        quotes=[
            "तुम्हारे नाना जी को बहुत पसंद थी",  # real (minus punctuation)
            "Dhakkan mat kholna beech mein",  # real, Hinglish, different case/punct
            "Pyaar se banao, swaad apne aap aayega",  # invented
        ]
    )
    out, rep = verify_recipe(r, hindi_transcript)
    assert out.quotes == ["तुम्हारे नाना जी को बहुत पसंद थी", "Dhakkan mat kholna beech mein"]
    assert rep.dropped_count == 1
    assert "Pyaar se banao" in rep.dropped[0]


def test_her_words_verified_across_scripts(hindi_transcript):
    r = Recipe(
        ingredients=[
            Ingredient(name="Wheat flour (atta)", her_words="एक मुट्ठी आटा", approx="~1 cup / 120 g"),
            Ingredient(name="Salt", her_words="अंदाज़ से नमक", approx="1/2 tsp"),
            Ingredient(name="Ghee", her_words="do chammach ghee", approx="~2 tbsp"),  # she never said this
        ]
    )
    out, rep = verify_recipe(r, hindi_transcript)
    assert out.ingredients[0].her_words == "एक मुट्ठी आटा"
    assert out.ingredients[1].her_words == "अंदाज़ से नमक"
    assert out.ingredients[1].approx == "~1/2 tsp"  # approximations are always marked
    assert out.ingredients[2].her_words == ""  # dropped, but the ingredient itself stays
    assert out.ingredients[2].name == "Ghee"
    assert rep.dropped_count == 1


def test_fuzzy_spacing_snaps_to_transcript_text(hindi_transcript):
    # "tel chhodde" (spacing slip) → transcript's "tel chhod de"
    out, rep = verify_recipe(Recipe(steps=[Step(text="Fry", her_cue="jab tak tel chhodde", start_sec=0)]), hindi_transcript)
    assert out.steps[0].her_cue == "jab tak tel chhod de"
    assert rep.dropped_count == 0 and len(rep.corrected) == 1


def test_short_unknown_words_are_not_fuzzed(hindi_transcript):
    idx = TranscriptIndex(hindi_transcript)
    assert idx.find("teel") is None
    assert idx.find("tel") is not None


def test_quotes_capped_at_three_and_deduped(hindi_transcript):
    r = Recipe(
        quotes=[
            "Dhakkan mat kholna beech mein",
            "dhakkan mat kholna, beech mein!",
            "सबसे पहले एक मुट्ठी आटा लो",
            "फिर थोड़ा सा हल्दी डालो",
            "ghee daalo",
        ]
    )
    out, _ = verify_recipe(r, hindi_transcript)
    assert len(out.quotes) == 3
    assert out.quotes[0] == "Dhakkan mat kholna beech mein"


def test_non_numeric_estimate_is_never_confident(hindi_transcript):
    r = Recipe(ingredients=[Ingredient(name="Salt", approx="~to taste", confidence="high"),
                            Ingredient(name="Hing", approx="~1 pinch", confidence="med")])
    out, _ = verify_recipe(r, hindi_transcript)
    assert [i.confidence for i in out.ingredients] == ["low", "med"]


def test_tip_that_is_also_a_warning_kept_once(hindi_transcript):
    r = Recipe(tips=["Dhakkan mat kholna!", "Use desi ghee"], warnings=["dhakkan mat kholna"])
    out, _ = verify_recipe(r, hindi_transcript)
    assert out.tips == ["Use desi ghee"] and out.warnings == ["dhakkan mat kholna"]


def test_high_confidence_needs_a_spoken_number(hindi_transcript):
    r = Recipe(ingredients=[
        Ingredient(name="Turmeric", her_words="", approx="~1/2 tsp", confidence="high"),
        Ingredient(name="Flour", her_words="एक मुट्ठी आटा", approx="~1 cup", confidence="high"),
        Ingredient(name="Water", her_words="do cup paani", approx="~2 cups", confidence="high"),
    ])
    out, _ = verify_recipe(r, hindi_transcript)
    assert [i.confidence for i in out.ingredients] == ["med", "high", "med"]  # "do cup paani" isn't in the transcript → dropped → med


def test_shared_amount_merged_into_one_ingredient():
    from conftest import make_transcript

    t = make_transcript([
        (55.5, "अब दाल, तुर, चना और मूंग,"),
        (58.4, "तीनों मिला के एक कटोरी,"),
        (61.3, "कुकर में हल्दी और नमक दाल के तीन सीटी,"),
    ])
    r = Recipe(ingredients=[
        Ingredient(name="Tur dal", her_words="तुर", approx="~1 cup", confidence="med"),
        Ingredient(name="Chana dal", her_words="चना", approx="~1 cup", confidence="high"),
        Ingredient(name="Moong dal", her_words="मूंग", approx="~1 cup", confidence="med"),
        Ingredient(name="Turmeric", her_words="हल्दी", approx="~1/2 tsp", confidence="low"),
        Ingredient(name="Salt", her_words="नमक", approx="~1/2 tsp", confidence="low"),  # same estimate, no "together" word
    ])
    out, _ = verify_recipe(r, t)
    assert [i.name for i in out.ingredients] == ["Tur dal, Chana dal and Moong dal (mixed)", "Turmeric", "Salt"]
    mixed = out.ingredients[0]
    assert mixed.her_words == "तुर, चना और मूंग, तीनों मिला के एक कटोरी"
    assert mixed.approx == "~1 cup all together" and mixed.confidence == "med"


def test_same_estimate_far_apart_not_merged(hindi_transcript):
    r = Recipe(ingredients=[
        Ingredient(name="Flour", her_words="एक मुट्ठी आटा", approx="~1 cup"),
        Ingredient(name="Ghee", her_words="ghee daalo", approx="~1 cup"),
    ])
    out, _ = verify_recipe(r, hindi_transcript)
    assert len(out.ingredients) == 2


def test_card_text_has_no_em_dashes_but_her_words_untouched(hindi_transcript):
    r = Recipe(story="Nanaji loved it — every Diwali", steps=[Step(text="Fry — until golden", her_cue="tel chhod de")],
               tips=["Use ghee—lots"], quotes=["Dhakkan mat kholna beech mein"])
    out, _ = verify_recipe(r, hindi_transcript)
    assert out.story == "Nanaji loved it, every Diwali"
    assert out.steps[0].text == "Fry, until golden" and out.tips == ["Use ghee, lots"]
    assert out.quotes == ["Dhakkan mat kholna beech mein"]
