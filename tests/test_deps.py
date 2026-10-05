"""Заявленное в манифесте против того, что код действительно импортирует.

Зачем отдельная проверка. Три библиотеки — shapely, pyshp и pypdf —
использовались и не были объявлены в `pyproject.toml`. Работало потому,
что они стояли в окружении, поставленные когда-то руками: проект зависел
от состояния машины, а не от своего описания. Вскрылось при пересоздании
`.venv`, случайно, а не проверкой.

Обычная проверка «импортируется ли пакет» этого НЕ ЛОВИТ, и вот почему:
почти все внешние модули подключаются лениво, внутри функций. Пакет
импортируется, `fca --help` работает, тесты на фикстурах проходят, а
отсутствие библиотеки всплывает только на конкретном пути расчёта — у
пользователя, а не у автора.

Поэтому смотрим не на импорт, а на ИСХОДНЫЙ ТЕКСТ: разбираем дерево,
собираем корневые имена всех внешних модулей и сверяем с манифестом.
Проверка не требует, чтобы библиотеки были установлены, — значит работает
и на чистой машине, и в CI до установки зависимостей.
"""

from __future__ import annotations

import ast
import pathlib
import sys
import tomllib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
# Сканируем И пакет, И инструменты: разрыв между заявленным и
# импортируемым не знает границ каталогов, а shapely мы потеряли именно
# так. Зависимости инструментов законно необязательны, но объявлены быть
# обязаны — сверяемся с объединением основных и необязательных групп.
SCAN = [ROOT / "flightcostapp", ROOT / "tools"]

# Имя пакета в манифесте не всегда совпадает с именем модуля в коде.
# Пары, которые расходятся, перечислены явно: угадывать по эвристике
# «убрать дефисы» — значит однажды промолчать на новом расхождении.
DIST_TO_MODULE = {
    "pyyaml": "yaml",
    "pyshp": "shapefile",
    "python-dateutil": "dateutil",
}


def _declared() -> set[str]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    out = set()
    groups = [data["project"]["dependencies"]]
    groups += list((data["project"].get("optional-dependencies") or {}).values())
    for group in groups:
        for spec in group:
            name = spec.split(">")[0].split("=")[0].split("<")[0].split("[")[0]
            name = name.strip().lower()
            out.add(DIST_TO_MODULE.get(name, name.replace("-", "_")))
    return out


def _imported() -> dict[str, set[str]]:
    """Корневые имена внешних модулей -> файлы, где встретились."""
    out: dict[str, set[str]] = {}
    paths = [q for root in SCAN if root.exists() for q in sorted(root.rglob("*.py"))]
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                # Относительный импорт — свой же модуль, `level` > 0.
                if node.level:
                    continue
                names = [node.module or ""]
            else:
                continue
            for n in names:
                root = n.split(".")[0]
                if not root or root in sys.stdlib_module_names:
                    continue
                if root in ("flightcostapp", "__future__"):
                    continue
                out.setdefault(root, set()).add(path.name)
    return out


class Dependencies(unittest.TestCase):

    def test_every_import_is_declared(self):
        """Импортируется — значит объявлено. Иначе установка соберётся и
        упадёт при работе, у чужого, на неожиданном пути."""
        declared, imported = _declared(), _imported()
        missing = {m: sorted(f) for m, f in imported.items() if m not in declared}
        self.assertEqual(
            missing, {},
            "не объявлены в pyproject.toml, а импортируются:\n  "
            + "\n  ".join(f"{m}: {', '.join(f)}" for m, f in sorted(missing.items()))
            + "\n\nименно так пропали shapely, pyshp и pypdf: ленивый импорт "
              "внутри функций не виден ни при установке, ни при запуске")

    def test_every_declared_is_used(self):
        """Обратная сторона: объявленное и не используемое.

        Не отказ мира, а мусор в манифесте — лишняя зависимость тянется
        в каждую установку и однажды сломает её конфликтом версий. Но
        падать на этом стоит: манифест описывает проект, а описание,
        которое врёт в одну сторону, скоро соврёт и в другую.
        """
        declared, imported = _declared(), set(_imported())
        # pytest не импортируется кодом — он его запускает. Группа `dev`
        # здесь законное исключение, и оно названо, а не обойдено молча.
        extra = sorted(declared - imported - {"pytest"})
        self.assertEqual(
            extra, [],
            f"объявлены и нигде не импортируются: {extra}. "
            f"Либо удалить, либо назвать причину прямо в манифесте")


if __name__ == "__main__":
    unittest.main(verbosity=2)
