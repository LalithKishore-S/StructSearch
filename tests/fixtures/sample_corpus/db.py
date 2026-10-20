def validate_user_input(value):
    """Reject empty or suspicious user input."""
    if not value or not isinstance(value, str):
        raise ValueError("invalid input")
    if ";" in value or "--" in value:
        raise ValueError("suspicious input")
    return value.strip()


def get_user(db, username):
    """Validate the username, then query the database with a parameter."""
    clean = validate_user_input(username)
    return db.execute("SELECT * FROM users WHERE name = ?", (clean,)).fetchone()


def find_user_unsafe(db, username):
    """Build the SQL string directly from user input without validation."""
    query = "SELECT * FROM users WHERE name = '" + username + "'"
    return db.execute(query).fetchall()


def count_rows(db, table_name):
    """Count rows in a table."""
    return db.execute("SELECT COUNT(*) FROM " + table_name).fetchone()[0]
