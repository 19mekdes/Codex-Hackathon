import unittest

from buggy import sum_numbers


class SumNumbersTests(unittest.TestCase):
    def test_includes_both_endpoints(self):
        self.assertEqual(sum_numbers(1, 4), 10)

    def test_single_number_range(self):
        self.assertEqual(sum_numbers(3, 3), 3)


if __name__ == "__main__":
    unittest.main()
