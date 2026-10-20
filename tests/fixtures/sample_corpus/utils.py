import re


def add(a, b):
    """Add two numbers."""
    return a + b


def slugify(text):
    """Convert text to a URL-friendly slug."""
    text = text.lower().strip()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def camel_to_snake(name):
    """Convert camelCase to snake_case."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


class Counter:
    def increment(self, amount=1):
        """Increase the internal count."""
        self.count = getattr(self, "count", 0) + amount
        return self.count
