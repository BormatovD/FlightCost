"""Переводы витрины: у каждой фразы есть английский и немецкий.

Каталог (`web/i18n.json`) — ключ-русская фраза. Тест ловит две поломки,
которые иначе видны только глазами в чужом языке:

  * фраза обёрнута в t(), а перевода нет — в английской витрине по-русски;
  * русский текст добавлен в скрипт или разметку БЕЗ t() — то же самое,
    но ещё и мимо каталога.

Шаги разбора и предупреждения порождает ядро на Python — они пока
по-русски намеренно и здесь не проверяются.
"""

from __future__ import annotations

import json
import pathlib
import re
import unittest

WEB = pathlib.Path(__file__).resolve().parents[1] / "flightcostapp" / "web"
CYR = re.compile(r"[А-Яа-яЁё]")
T_CALL = re.compile(r'(?<![\w$.])_t\("((?:[^"\\]|\\.)*)"\)')


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


class I18n(unittest.TestCase):

    # Страницы с переводом из одного каталога. Отчёт по парку (Ф5)
    # собирается на сервере: его фразы — вызовы T("…") в Python и
    # проверяются отдельно (DOC_T), но сиротами в каталоге не считаются.
    PAGES = ("serve.html",)
    DOC = WEB.parent / "fleetreport_doc.py"
    DOC_T = re.compile(r'(?<![\w$.])T\("((?:[^"\\]|\\.)*)"\)')

    @classmethod
    def setUpClass(cls):
        cls.cat = json.loads((WEB / "i18n.json").read_text(encoding="utf-8"))
        markup, script = [], []
        for name in cls.PAGES:
            html = (WEB / name).read_text(encoding="utf-8")
            a = html.index('<script type="module">')
            markup.append(html[:a])
            script.append(html[a:html.rindex("</script>")])
        cls.markups, cls.scripts = markup, script
        cls.script = "\n".join(script)
        cls.doc_keys = {norm(k) for k in cls.DOC_T.findall(cls.DOC.read_text(encoding="utf-8"))}

    def test_report_phrases_are_translated(self):
        for lang in ("en", "de"):
            missing = sorted(k for k in self.doc_keys if k not in self.cat[lang])
            self.assertEqual(missing, [], f"отчёт по парку без перевода на {lang}: {missing[:10]}")

    def test_every_wrapped_phrase_is_translated(self):
        keys = {norm(json.loads('"' + k + '"')) for k in T_CALL.findall(self.script)}
        for lang in ("en", "de"):
            missing = sorted(k for k in keys if k not in self.cat[lang])
            self.assertEqual(missing, [], f"нет перевода на {lang}: {missing[:10]}")

    def test_static_markup_is_translated(self):
        texts = set()
        for markup in self.markups:
            body = re.sub(r"<!--[\s\S]*?-->", "", markup[markup.index("<body"):])
            texts |= {norm(m) for m in re.findall(r">([^<]+)<", body) if CYR.search(m)}
            texts |= {norm(m) for m in re.findall(r'(?:placeholder|title|aria-label)="([^"]*)"', body)
                      if CYR.search(m)}
        for lang in ("en", "de"):
            missing = sorted(k for k in texts if k not in self.cat[lang])
            self.assertEqual(missing, [], f"разметка без перевода на {lang}: {missing[:10]}")

    def test_no_unwrapped_russian_in_script(self):
        s = T_CALL.sub("", self.script)
        s = re.sub(r"/\*[\s\S]*?\*/", "", s)
        s = re.sub(r"(^|[\s;{}(),])//[^\n]*", r"\1", s)
        # Законный русский без t(): регулярные выражения (ищут кириллицу или
        # русские предупреждения ядра — их текст приходит с сервера по-русски)
        # и служебные сообщения в консоль разработчика.
        s = re.sub(r"([\[(,=:!&|?]\s*)/(?:\\.|\[[^\]\n]*\]|[^/\n\\])+/[gimsuy]*", r"\1", s)
        s = re.sub(r"console\.\w+\([^\n]*\)", "", s)
        left = [ln.strip()[:90] for ln in s.splitlines() if CYR.search(ln)]
        self.assertEqual(left, [], "русский текст в скрипте мимо t(): " + " | ".join(left[:5]))

    def test_translation_function_is_not_shadowed(self):
        """Функция перевода называется так, как ни одна переменная витрины.

        Первая версия назвала её `t` — а `t` в витрине частое имя локальной
        переменной (тип самолёта, строка таблицы). Внутри двенадцати
        функций вызов перевода обращался к объекту и падал: «t is not a
        function», запуск витрины останавливался на третьей строке, а
        синтаксис при этом был безупречен.
        """
        binds = re.findall(r"(?:const|let|var)\s+_t\b|(?<![\w$])_t\s*=>|"
                           r"\(\s*_t\s*[,)=]|,\s*_t\s*[,)]|function\s+\w+\s*\([^)]*\b_t\b",
                           self.script)
        self.assertEqual(binds, [], f"имя функции перевода перекрыто: {binds}")
        for sc in self.scripts:
            self.assertEqual(len(re.findall(r"function _t\(", sc)), 1)

    def test_catalogue_has_no_orphans(self):
        keys = {norm(json.loads('"' + k + '"')) for k in T_CALL.findall(self.script)}
        for markup in self.markups:
            body = re.sub(r"<!--[\s\S]*?-->", "", markup[markup.index("<body"):])
            keys |= {norm(m) for m in re.findall(r">([^<]+)<", body) if CYR.search(m)}
            keys |= {norm(m) for m in re.findall(r'(?:placeholder|title|aria-label)="([^"]*)"', body)}
            t = re.search(r"<title>([^<]+)</title>", markup)
            if t:
                keys.add(norm(t.group(1)))
        keys |= self.doc_keys
        orphans = sorted(set(self.cat["en"]) - keys)
        self.assertEqual(orphans, [], f"в каталоге фразы, которых нет на странице: {orphans[:10]}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
