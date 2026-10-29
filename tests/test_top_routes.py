"""Маршруты для сбора цен: группы по странам и список внутриафриканских линий."""
import importlib.util, pathlib, sys, unittest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("top_routes", ROOT / "tools" / "top_routes.py")
TR = importlib.util.module_from_spec(spec)
spec.loader.exec_module(TR)


class TopRoutes(unittest.TestCase):
    def test_groups(self):
        self.assertEqual(TR.group_of("IN", "IN"), "india-dom")
        self.assertEqual(TR.group_of("DE", "IN"), "india-intl")
        self.assertEqual(TR.group_of("KE", "IN"), "india-intl", "Индия главнее Африки")
        self.assertEqual(TR.group_of("DE", "EG"), "africa")
        self.assertEqual(TR.group_of("DE", "TR"), "europe")
        self.assertIsNone(TR.group_of("DE", "US"))

    def test_africa_core_list(self):
        pairs = yaml.safe_load((ROOT / "tools" / "routes_africa_core.yaml").read_text(encoding="utf-8"))["pairs"]
        norm = [tuple(sorted(p.split("-"))) for p in pairs]
        self.assertEqual(len(norm), len(set(norm)), "повтор пары")
        for a, b in norm:
            self.assertRegex(a + b, r"^[A-Z]{8}$")
            self.assertTrue(a[0] in "DFGH" and b[0] in "DFGH", f"{a}-{b}: не африканский код ИКАО")


if __name__ == "__main__":
    unittest.main()
