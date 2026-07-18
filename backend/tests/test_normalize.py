from app.taste.normalize import norm_key, norm_name


def test_lowercases_and_strips_punctuation():
    assert norm_name("Don't Stop Me Now!") == "dont stop me now"


def test_strips_feat_clauses():
    assert norm_name("CRG (feat. Dave)") == "crg"
    assert norm_name("OBVIOUS [feat. Hasan Raheem]") == "obvious"
    assert norm_name("4U feat. Someone") == "4u"


def test_folds_unicode_accents():
    assert norm_name("Beyoncé") == "beyonce"


def test_collapses_whitespace():
    assert norm_name("  A   B  ") == "a b"


def test_norm_key_artist_only_and_pair():
    assert norm_key("Central Cee") == "central cee"
    assert norm_key("Central Cee", "CRG (feat. Dave)") == "central cee|crg"
