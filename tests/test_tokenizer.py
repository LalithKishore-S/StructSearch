from structsearch.indexing import (
    split_identifier,
    tokenize_query,
    tokenize_text,
    tokenize_words,
)


def test_split_snake_camel_pascal_acronym():
    assert split_identifier("validate_user_input") == ["validate", "user", "input"]
    assert split_identifier("camelCaseName") == ["camel", "case", "name"]
    assert split_identifier("FileNotFoundError") == ["file", "not", "found", "error"]
    assert split_identifier("HTTPServer") == ["http", "server"]
    assert split_identifier("getHTTPResponse") == ["get", "http", "response"]
    assert split_identifier("os.path") == ["os", "path"]


def test_tokenize_words_drops_stopwords_short_and_numbers():
    assert tokenize_words(["FileNotFoundError"]) == ["file", "found", "error"]
    assert tokenize_words(["x", "n1", "42", "the", "is_valid"]) == ["n1", "valid"]


def test_tokenize_text_finds_words_in_strings_and_code():
    tokens = tokenize_text('db.execute("SELECT * FROM users WHERE name = ?")')
    assert tokens == ["db", "execute", "select", "users", "where", "name"]


def test_tokenize_query_drops_query_words_but_keeps_get():
    assert tokenize_query("Find functions that validate user input before database access") == [
        "validate", "user", "input", "before", "database", "access",
    ]
    assert tokenize_query("get_user") == ["get", "user"]
    assert tokenize_query("find all the functions") == []


def test_no_stemming_documented_behaviour():
    assert tokenize_text("validate validation") == ["validate", "validation"]
