"""Demo module for the SQL-construction candidate scan (never imported or executed, only parsed).

Each function shows one shape the scan reports or leaves out; see README_STEP17.md.
"""
from flask import request


def validate_name(value):
    """Reject names with quotes or semicolons."""
    if "'" in value or ";" in value:
        raise ValueError("bad name")
    return value


def search_by_name(db):
    """Name taken from the HTTP request and concatenated into the query."""
    name = request.args.get("name")
    sql = "SELECT * FROM users WHERE name = '" + name + "'"
    return db.execute(sql).fetchall()


def cli_lookup(db):
    """Name typed by the user and concatenated into the query."""
    name = input("name: ")
    return db.execute("SELECT * FROM users WHERE name = '" + name + "'").fetchall()


def search_fstring(db, name):
    return db.execute(f"SELECT * FROM users WHERE name = '{name}'").fetchall()


def search_format(db, name):
    query = "SELECT * FROM users WHERE name = '{}'".format(name)
    return db.execute(query).fetchall()


def search_percent(db, name):
    return db.execute("SELECT * FROM users WHERE name = '%s'" % name).fetchall()


def search_validated_first(db, name):
    validate_name(name)
    sql = "SELECT * FROM users WHERE name = '" + name + "'"
    return db.execute(sql).fetchall()


def search_validated_value(db, name):
    clean = validate_name(name)
    return db.execute("SELECT * FROM users WHERE name = '" + clean + "'").fetchall()


def search_parameterized(db, name):
    return db.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchall()


def run_query(db, sql):
    return db.execute(sql).fetchall()


def handler(db, form_value):
    return run_query(db, "SELECT * FROM users WHERE name = '" + form_value + "'")


def lookup(db, user):
    return search_percent(db, user)


def endpoint(db, text):
    return lookup(db, text)


def constant_query(db):
    return db.execute("SELECT * FROM users WHERE active = " + "1").fetchall()
