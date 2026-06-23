from proofcheck.normalize import fold_digits, normalize, reverse_words, strip_punct


def test_baseline_casefold_and_whitespace():
    assert normalize("  John   SMITH ") == "john smith"


def test_normalize_is_deterministic():
    a = normalize("Café  Núñez", normalize_digits=True, strip_punctuation=True)
    b = normalize("Café  Núñez", normalize_digits=True, strip_punctuation=True)
    assert a == b


def test_fold_digits_arabic_indic():
    # Arabic-Indic digits ١٢٣ -> 123
    assert fold_digits("١٢٣") == "123"


def test_normalize_digits_flag():
    assert normalize("Room ١٠", normalize_digits=True) == "room 10"
    # Without the flag, digits are left as-is.
    assert normalize("Room ١٠", normalize_digits=False) != "room 10"


def test_strip_punct_replaces_with_space():
    assert "cc 101" in normalize("CC-101", strip_punctuation=True)
    assert "-" not in strip_punct("CC-101")


def test_reverse_words():
    assert reverse_words("john smith") == "smith john"
    assert reverse_words("madonna") == "madonna"


def test_none_is_empty():
    assert normalize(None) == ""
