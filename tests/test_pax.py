"""Пассажиров на рейсе — целое число (решение 229)."""

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from flightcostapp.econ import pax_count  # noqa: E402


class PaxCount(unittest.TestCase):

    def test_integer_half_up(self):
        self.assertEqual(pax_count(170, 0.82), 139)      # 139,4
        self.assertEqual(pax_count(170, 0.85), 145)      # 144,5 — вверх, не к чётному
        self.assertEqual(pax_count(150, 0.70), 105)      # 104,999… не становится 104
        self.assertIsInstance(pax_count(180, 0.8), int)

    def test_compare_reproduces_route(self):
        # Сравнение типов задаёт загрузку как пассажиры / кресла: число
        # пассажиров обязано вернуться тем же целым.
        for seats in (100, 150, 170, 186, 220):
            for pax in range(1, seats + 1):
                self.assertEqual(pax_count(seats, pax / seats), pax)


if __name__ == "__main__":
    unittest.main()
