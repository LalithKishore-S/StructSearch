import json


def read_config_safe(path):
    """Read a JSON config file, handling missing files and bad JSON."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        return None


def write_log(path, message):
    """Append a message to a log file."""
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def read_lines(path):
    """Read all lines of a file with no error handling."""
    with open(path) as handle:
        return handle.readlines()
