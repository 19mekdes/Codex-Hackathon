def item_count(items):
    """Return the number of items, treating None as an empty collection."""
    if items is None:
        return 0
    return len(items)
