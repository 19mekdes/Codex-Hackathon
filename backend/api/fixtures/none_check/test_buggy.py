import unittest

from buggy import item_count


class ItemCountTests(unittest.TestCase):
    def test_none_is_empty(self):
        self.assertEqual(item_count(None), 0)

    def test_counts_items(self):
        self.assertEqual(item_count(["a", "b"]), 2)


if __name__ == "__main__":
    unittest.main()
