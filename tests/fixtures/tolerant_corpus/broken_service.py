import os


class Repo:
    def good_method(self, x):
        """Fine method."""
        if x:
            return self.good_method(x - 1)
        return 0

    def half_broken(self, rows):
        total = 0
        for row in rows:
            total += row ??? 2
            if row:
                total += 1
        return total

    def unclosed(self, path):
        handle = open(path
        return handle.read()


def after_everything(items):
    for item in items:
        try:
            item.run()
        except Exception:
            pass
    return len(items)


def header_broken(x:
    return x
