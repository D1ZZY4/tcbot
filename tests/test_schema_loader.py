# © Copyright 2024 - 2026 Transsion Core
# © Copyright 2024 - 2026 Dizzy
# © Copyright 2026 Ave Labs

"""The schema splitter keeps quoted regions and comments intact."""

from __future__ import annotations

from tcbot.database.schema.loader import split_statements


def test_a_plain_script_splits_at_each_semicolon() -> None:
    assert split_statements("SELECT 1; SELECT 2;") == ["SELECT 1", "SELECT 2"]


def test_a_semicolon_in_a_string_does_not_end_the_statement() -> None:
    statements = split_statements("INSERT INTO t VALUES ('a;b'); SELECT 2;")
    assert statements == ["INSERT INTO t VALUES ('a;b')", "SELECT 2"]


def test_a_doubled_quote_stays_inside_the_string() -> None:
    statements = split_statements("SELECT 'it''s; fine'; SELECT 2;")
    assert statements == ["SELECT 'it''s; fine'", "SELECT 2"]


def test_an_escape_string_honours_a_backslash_quote() -> None:
    statements = split_statements(r"SELECT E'it\'s; ok'; SELECT 2;")
    assert statements == [r"SELECT E'it\'s; ok'", "SELECT 2"]


def test_a_dollar_quoted_body_keeps_its_semicolons() -> None:
    script = (
        "CREATE FUNCTION f() RETURNS void AS $$ "
        "BEGIN PERFORM 1; PERFORM 2; END; "
        "$$ LANGUAGE plpgsql; SELECT 2;"
    )
    statements = split_statements(script)
    assert len(statements) == 2
    assert statements[0].startswith("CREATE FUNCTION f()")
    assert statements[0].endswith("LANGUAGE plpgsql")
    assert "PERFORM 1; PERFORM 2;" in statements[0]


def test_a_line_comment_hides_its_semicolon() -> None:
    statements = split_statements("SELECT 1; -- not; a; statement\nSELECT 2;")
    assert len(statements) == 2
    assert statements[0] == "SELECT 1"
    assert statements[1].endswith("SELECT 2")


def test_a_block_comment_hides_its_semicolon() -> None:
    statements = split_statements("SELECT 1; /* not; a; statement */ SELECT 2;")
    assert len(statements) == 2
    assert statements[0] == "SELECT 1"
    assert statements[1].endswith("SELECT 2")


def test_a_nested_block_comment_stays_one_comment() -> None:
    statements = split_statements(
        "SELECT 1; /* outer /* inner; */ still; outer */ SELECT 2;"
    )
    assert len(statements) == 2
    assert statements[0] == "SELECT 1"
    assert statements[1].endswith("SELECT 2")


def test_a_double_quoted_identifier_keeps_its_semicolon() -> None:
    statements = split_statements('SELECT "a;b" FROM t; SELECT 2;')
    assert statements == ['SELECT "a;b" FROM t', "SELECT 2"]


def test_an_unterminated_dollar_body_consumes_the_rest() -> None:
    statements = split_statements("SELECT 1; $$ still open;")
    assert statements == ["SELECT 1", "$$ still open;"]
