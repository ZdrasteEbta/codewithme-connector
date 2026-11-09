"""Проверка кода без запуска: ошибки написания и недостающие библиотеки."""
import ast
import builtins
import difflib
import json
import keyword
import os
import re
import subprocess
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path

from pyflakes import checker as flakes
from pyflakes import messages as flake

from hints import NODE_BUILTINS, NPM_NAMES, PIP_NAMES, say

# Эти имена добавляет модуль site, которого нет в собранном приложении
flakes.Checker.builtIns = set(flakes.Checker.builtIns) | {"exit", "quit", "copyright", "credits", "license", "help"}

MAX_PROBLEMS = 50
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
JS_PREFIX = "(async function(){"  # сайт запускает код внутри асинхронной функции: там законны await и return


@dataclass
class Problem:
    line: int
    col: int
    end: int
    message: str
    example: str = ""


@dataclass
class Missing:
    name: str
    package: str
    kind: str  # pip | npm


@dataclass
class Report:
    checked: bool = True
    problems: list = field(default_factory=list)
    missing: list = field(default_factory=list)


def family_of(language: str) -> str:
    if language in ("rust", "macroquad"):
        return "rust"
    if language == "html":
        return "html"
    if language in ("javascript", "node", "dom"):
        return "js"
    return "python"


def check(code: str, language: str, locale: str, env: dict | None, task_folder: str | None) -> Report:
    family = family_of(language)
    if family == "python":
        report = check_python(code, locale, env, task_folder)
    elif family == "js":
        report = check_js(code, language, locale, env)
    elif family == "rust" and language == "rust":
        report = check_rust(code, locale, env)
    else:
        return Report(checked=False)
    report.problems = report.problems[:MAX_PROBLEMS]
    return report


def _run(args, timeout=8):
    try:
        return subprocess.run(
            args, stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _close_word(word: str, candidates) -> str:
    """Похожее слово без учёта регистра: Print → print, true → True."""
    lowered = {c.lower(): c for c in candidates}
    found = difflib.get_close_matches(word.lower(), list(lowered), 1, 0.75)
    return lowered[found[0]] if found else ""


# --- Python ---

_CLOSERS = {"(": ")", "[": "]", "{": "}"}
_PY_SYNTAX = [
    (r"expected ':'", "colon"),
    (r"invalid syntax\. Maybe you meant '=='", "compare"),
    (r"'([(\[{])' was never closed", "not_closed"),
    (r"unmatched '([)\]}])'", "unmatched"),
    (r"closing parenthesis '(.)' does not match opening parenthesis '(.)'", "wrong_close"),
    (r"unterminated (triple-quoted )?(f-)?string", "string"),
    (r"unexpected indent", "unexpected_indent"),
    (r"expected an indented block", "need_indent"),
    (r"unindent does not match", "bad_dedent"),
    (r"inconsistent use of tabs", "tabs"),
    (r"Missing parentheses in call to 'print'", "print_parens"),
    (r"Perhaps you forgot a comma", "comma"),
    (r"cannot assign to", "assign"),
    (r"invalid (decimal|hexadecimal|octal|binary) literal", "bad_number"),
    (r"leading zeros", "leading_zero"),
    (r"expected 'except' or 'finally'", "try"),
    (r"invalid (non-printable )?character", "bad_char"),
    (r"f-string", "fstring"),
    (r"expected '\('", "def_parens"),
    (r"invalid syntax", "syntax"),
]
_COMMON_WORDS = ["if", "elif", "else", "for", "while", "def", "class", "return", "import", "from", "try", "except", "print", "input"]


def _syntax_problem(err: SyntaxError, code: str, locale: str) -> Problem:
    source = (err.text or "").rstrip("\r\n")
    plain = source.strip()
    line = max((err.lineno or 1) - 1, 0)
    col = max((err.offset or 1) - 1, 0)
    end = col + 1
    if err.end_lineno == err.lineno and err.end_offset and err.end_offset - 1 > col:
        end = err.end_offset - 1

    message, example = err.msg, ""
    for pattern, key in _PY_SYNTAX:
        m = re.search(pattern, err.msg)
        if not m:
            continue
        if key == "assign" and re.match(r"(if|elif|while)\b", plain):
            key = "compare"
        if key == "not_closed":
            message, example = say(locale, key, m.group(1)), source_at(code, line).strip() + _CLOSERS[m.group(1)]
        elif key in ("unmatched",):
            message = say(locale, key, m.group(1))
        elif key == "wrong_close":
            message = say(locale, key, m.group(2), m.group(1))
        elif key == "bad_char":
            bad = re.search(r"'(.)'", err.msg) or re.search(r"U\+([0-9A-Fa-f]+)", err.msg)
            shown = (bad.group(1) if bad and "U+" not in bad.group(0) else plain[col:col + 1]) or "?"
            message = say(locale, key, shown)
        else:
            message = say(locale, key)
        if key == "colon" and plain:
            example = plain + ":"
        elif key == "compare":
            example = re.sub(r"(?<![=!<>])=(?!=)", "==", plain, count=1)
        elif key == "string" and plain:
            quote = next((c for c in plain[col:] if c in "\"'"), '"')
            example = plain + quote
        elif key == "need_indent" and plain:
            example = "    " + plain
        elif key == "unexpected_indent":
            example = plain
        elif key == "print_parens":
            example = "print(" + plain.removeprefix("print").strip() + ")"
        elif key == "assign":
            example = "x = 5"
        elif key == "def_parens":
            example = "def name():"
        elif key == "syntax":
            first = re.match(r"[A-Za-z_]+", plain)
            if first and not keyword.iskeyword(first.group(0)):
                close = _close_word(first.group(0), _COMMON_WORDS)
                if close and close != first.group(0):
                    message = say(locale, "typo_keyword", first.group(0), close)
                    example = close + plain[len(first.group(0)):]
        break
    return Problem(line, col, end, message, example)


def source_at(code: str, line: int) -> str:
    rows = code.split("\n")
    return rows[line].rstrip("\r") if 0 <= line < len(rows) else ""


def _char_col(code: str, line: int, byte_col: int) -> int:
    """В дереве разбора колонка считается в байтах, а в редакторе в символах."""
    return len(source_at(code, line).encode("utf-8")[:byte_col].decode("utf-8", "ignore"))


def _word_end(code: str, line: int, col: int) -> int:
    m = re.compile(r"\w+").match(source_at(code, line), col)
    return m.end() if m else col + 1


def _defined_names(tree) -> set:
    names = set(dir(builtins))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


def _flake_problems(tree, code: str, locale: str) -> list:
    found = flakes.Checker(tree, filename="main.py", withDoctest=False).messages
    known = _defined_names(tree)
    problems = []
    for item in sorted(found, key=lambda m: (m.lineno, m.col)):
        line = item.lineno - 1
        col = _char_col(code, line, item.col)
        end = _word_end(code, line, col)
        example = ""
        if isinstance(item, flake.UndefinedName):
            name = item.message_args[0]
            close = _close_word(name, sorted(known - {name}))
            if close:
                message = say(locale, "undefined_maybe", name, close)
                example = re.sub(rf"\b{re.escape(name)}\b", close, source_at(code, line).strip(), count=1)
            else:
                message, example = say(locale, "undefined", name), f"{name} = 0"
        elif isinstance(item, flake.UndefinedLocal):
            message = say(locale, "before_assign", item.message_args[0])
        elif isinstance(item, flake.DuplicateArgument):
            message = say(locale, "duplicate_arg", item.message_args[0])
        elif isinstance(item, flake.ReturnOutsideFunction):
            message = say(locale, "return_outside")
        elif isinstance(item, (flake.ContinueOutsideLoop, flake.BreakOutsideLoop)):
            message = say(locale, "loop_outside")
        elif isinstance(item, flake.YieldOutsideFunction):
            message = say(locale, "await_outside")
        else:
            continue  # неиспользованные переменные и импорты ошибкой не считаем
        problems.append(Problem(line, col, end, message, example))
    return problems


def _optional_imports(tree) -> set:
    """Импорты внутри try с except ImportError написаны так, чтобы работать и без библиотеки."""
    optional = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        guarded = any(
            h.type is None or re.search(r"ImportError|ModuleNotFoundError|Exception", ast.dump(h.type))
            for h in node.handlers
        )
        if guarded:
            for inner in node.body:
                optional.update(id(n) for n in ast.walk(inner))
    return optional


def _tree_imports(tree, code: str):
    optional = _optional_imports(tree)
    for node in ast.walk(tree):
        if id(node) in optional:
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0], node.lineno - 1
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            yield node.module.split(".")[0], node.lineno - 1


_IMPORT_LINE = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_]\w*)", re.M)


def _text_imports(code: str):
    for m in _IMPORT_LINE.finditer(code):
        yield m.group(1), code.count("\n", 0, m.start(1))


def site_packages(env: dict):
    root = Path(env["pythonExe"]).parent.parent
    if os.name == "nt":
        return root / "Lib" / "site-packages"
    return next(iter(sorted((root / "lib").glob("python*/site-packages"))), None)


def installed_modules(env: dict) -> set:
    folder = site_packages(env) if env.get("python") else None
    names = set()
    if folder is None:
        return names
    try:
        for entry in os.scandir(folder):
            if entry.is_dir():
                if not entry.name.endswith((".dist-info", ".data", ".libs")):
                    names.add(entry.name)
            elif entry.name.endswith((".py", ".pyd", ".so")):
                names.add(entry.name.split(".")[0])
    except OSError:
        pass
    return names


def _import_problems(imports, code: str, locale: str, env: dict, task_folder: str | None):
    installed = installed_modules(env)
    problems, missing, seen = [], [], set()
    for name, line in imports:
        if name in seen or name in sys.stdlib_module_names or name in installed or name == "__future__":
            continue
        seen.add(name)
        if task_folder and (Path(task_folder) / f"{name}.py").exists():
            continue
        m = re.compile(rf"\b{re.escape(name)}\b").search(source_at(code, line))
        col = m.start() if m else 0
        end = m.end() if m else col + 1
        package = PIP_NAMES.get(name)
        if package:
            missing.append(Missing(name, package, "pip"))
            problems.append(Problem(line, col, end, say(locale, "not_installed", name)))
            continue
        close = _close_word(name, list(PIP_NAMES) + [n for n in sys.stdlib_module_names if not n.startswith("_")])
        if close:
            problems.append(Problem(line, col, end, say(locale, "unknown_module_maybe", name, close), source_at(code, line).strip().replace(name, close, 1)))
        else:
            problems.append(Problem(line, col, end, say(locale, "unknown_module", name)))
    return problems, missing


def check_python(code: str, locale: str, env: dict | None, task_folder: str | None) -> Report:
    report = Report()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = compile(code, "main.py", "exec", ast.PyCF_ONLY_AST, dont_inherit=True)
    except SyntaxError as err:
        report.problems.append(_syntax_problem(err, code, locale))
        imports = list(_text_imports(code))
    except (ValueError, RecursionError, MemoryError):
        return report
    else:
        report.problems.extend(_flake_problems(tree, code, locale))
        imports = list(_tree_imports(tree, code))
    if env:
        extra, report.missing = _import_problems(imports, code, locale, env, task_folder)
        report.problems = sorted(report.problems + extra, key=lambda p: (p.line, p.col))
    return report


# --- JavaScript ---

_JS_ERRORS = [
    (r"missing \) after argument list", "js_call", 0),
    (r"Unexpected end of input", "js_end", 0),
    (r"Invalid or unexpected token", "js_quote", 0),
    (r"Unexpected token '(.+)'", "js_token", 1),
    (r"Unexpected identifier '(.+)'", "js_token", 1),
    (r"Unexpected (string|number|template string)", "js_token", 1),
    (r"Identifier '(.+)' has already been declared", "js_redeclared", 1),
    (r"Missing initializer in const", "js_const", 0),
    (r"Invalid left-hand side in assignment", "js_assign", 0),
    (r"Cannot use import statement", "js_import", 0),
    (r"Missing catch or finally", "js_try", 0),
]
_JS_EXAMPLES = {"js_const": "const x = 5;", "js_import": 'const name = require("name");'}
_JS_NOISE = re.compile(r"//[^\n]*|/\*.*?\*/|(\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'|`(?:\\.|[^`\\])*`)", re.S)
_REQUIRE = re.compile(r"\brequire\(\s*[\"']([^\"'\n]+)[\"']\s*\)")
_JSX = re.compile(r"<[A-Za-z][\w.]*(\s[^<>]*)?/?>|<>")


def _js_requires(code: str):
    """Подключения библиотек вне комментариев."""
    visible = _JS_NOISE.sub(lambda m: m.group(1) or " " * len(m.group(0)), code)
    for m in _REQUIRE.finditer(visible):
        yield m.group(1), visible.count("\n", 0, m.start()), m.start(1) - (visible.rfind("\n", 0, m.start(1)) + 1), m.end(1) - (visible.rfind("\n", 0, m.start(1)) + 1)


def _npm_installed(env: dict, name: str) -> bool:
    return (Path(env["nodeModules"]) / name / "package.json").exists()


def check_js(code: str, language: str, locale: str, env: dict | None) -> Report:
    if not env or not env.get("node"):
        return Report(checked=False)
    report = Report()
    if language != "dom":
        seen = set()
        for full, line, col, end in _js_requires(code):
            name = full.removeprefix("node:")
            if full.startswith((".", "/")) or name.split("/")[0] in NODE_BUILTINS or name in seen or _npm_installed(env, name):
                continue
            seen.add(name)
            if name in NPM_NAMES:
                report.missing.append(Missing(name, NPM_NAMES[name], "npm"))
                report.problems.append(Problem(line, col, end, say(locale, "not_installed", name)))
            else:
                report.problems.append(Problem(line, col, end, say(locale, "unknown_module", name)))

    if language == "dom" and _JSX.search(_JS_NOISE.sub(lambda m: '""' if m.group(1) else "", code)):
        report.checked = False  # JSX собирает браузер, а node его не понимает
        return report

    source = Path(env["tmp"]) / "ide-check.js"
    try:
        source.write_text(JS_PREFIX + code + "\n})", encoding="utf-8")
    except OSError:
        return report
    done = _run([env["nodeExe"], "--check", str(source)])
    if done and done.returncode != 0:
        problem = _node_problem(done.stderr, code, locale)
        if problem:
            report.problems.append(problem)
    report.problems.sort(key=lambda p: (p.line, p.col))
    return report


def _node_problem(stderr: str, code: str, locale: str):
    rows = stderr.replace("\r", "").split("\n")
    if not rows or not (m := re.search(r":(\d+)$", rows[0])):
        return None
    line = int(m.group(1)) - 1
    if line > code.count("\n"):  # ошибка на закрывающей скобке обёртки: код ученика оборвался раньше
        rows_of_code = code.rstrip().split("\n")
        return Problem(len(rows_of_code) - 1, max(len(rows_of_code[-1]) - 1, 0), len(rows_of_code[-1]), say(locale, "js_end"))
    caret = next((r for r in rows[1:6] if re.fullmatch(r"\s*\^+\s*", r)), "")
    col = len(caret) - len(caret.lstrip()) if caret else 0
    end = col + max(caret.count("^"), 1)
    if line == 0:
        col, end = max(col - len(JS_PREFIX), 0), max(end - len(JS_PREFIX), 1)
    error = next((r for r in rows if re.match(r"\w*Error: ", r)), "")
    text = error.split(": ", 1)[-1]
    for pattern, key, groups in _JS_ERRORS:
        found = re.search(pattern, text)
        if found:
            message = say(locale, key, found.group(1)) if groups else say(locale, key)
            return Problem(line, col, end, message, _JS_EXAMPLES.get(key, ""))
    return Problem(line, col, end, text) if text else None


# --- Rust ---

_RS_ERRORS = [
    (r"expected `;`", "rs_semicolon", 0),
    (r"(unclosed delimiter|mismatched closing delimiter|unexpected closing delimiter)", "rs_delimiter", 0),
    (r"cannot find value `(\w+)`", "rs_undefined", 1),
    (r"cannot find function `(\w+)`", "rs_function", 1),
    (r"cannot find macro `(\w+)`", "rs_macro", 1),
    (r"mismatched types", "rs_types", 0),
    (r"cannot borrow `(\w+)` as mutable", "rs_mut", 1),
    (r"cannot assign twice to immutable variable `(\w+)`", "rs_mut", 1),
    (r"(?:borrow|use) of moved value: `(\w+)`", "rs_moved", 1),
    (r"unresolved import|use of unresolved module|use of undeclared crate|failed to resolve", "rs_crate", 0),
]


def check_rust(code: str, locale: str, env: dict | None) -> Report:
    if not env or not env.get("rust"):
        return Report(checked=False)
    report = Report()
    tmp = Path(env["tmp"])
    source = tmp / "ide-check.rs"
    try:
        source.write_text(code, encoding="utf-8")
    except OSError:
        return report
    done = _run([
        env["rustcExe"], "--edition", "2021", "--crate-name", "main", "--color", "never", "--error-format=json",
        "-Awarnings", "--emit=metadata", "-o", str(tmp / "ide-check.rmeta"), str(source),
    ], timeout=12)
    if done is None:
        return report
    for row in done.stderr.splitlines():
        try:
            item = json.loads(row)
        except ValueError:
            continue
        if item.get("level") != "error":
            continue
        span = next((s for s in item.get("spans", []) if s.get("is_primary")), None)
        if span:
            report.problems.append(_rust_problem(item, span, locale))
    report.problems.sort(key=lambda p: (p.line, p.col))
    return report


def _rust_problem(item: dict, span: dict, locale: str) -> Problem:
    text = item.get("message", "")
    message, example = text, ""
    for pattern, key, groups in _RS_ERRORS:
        found = re.search(pattern, text)
        if found:
            message = say(locale, key, found.group(1)) if groups else say(locale, key)
            if key == "rs_types":
                example = span.get("label") or ""
            break
    line = span["line_start"] - 1
    col = span["column_start"] - 1
    end = span["column_end"] - 1 if span["line_end"] == span["line_start"] else col + 1
    return Problem(line, col, max(end, col + 1), message, example)


# --- подписи функций Python ---


class PythonSignatures:
    """Спрашивает jedi о функции под курсором. Держит окружение ученика: так видны его библиотеки."""

    def __init__(self):
        self.executable = None
        self.environment = None

    def reset(self) -> None:
        self.executable, self.environment = None, None
        try:
            import jedi.cache

            jedi.cache.clear_time_caches(delete_all=True)
        except Exception:  # noqa: BLE001 кеш подсказок не должен мешать работе
            pass

    def _environment(self, env: dict | None):
        from jedi.api.environment import Environment, InterpreterEnvironment

        executable = env["pythonExe"] if env and env.get("python") else ""
        if self.environment is None or executable != self.executable:
            self.executable = executable
            try:
                self.environment = Environment(executable) if executable else InterpreterEnvironment()
            except Exception:  # noqa: BLE001 окружение могло сломаться: подсказка из встроенного
                self.environment = InterpreterEnvironment()
        return self.environment

    def lookup(self, code: str, line: int, col: int, env: dict | None, folder: str | None):
        try:
            import jedi

            project = jedi.Project(folder or os.getcwd(), smart_sys_path=False)
            found = jedi.Script(code, environment=self._environment(env), project=project).get_signatures(line, col)
            if not found:
                return None
            best = next((s for s in found if s.index is not None), found[0])
            doc = (best.docstring(raw=True) or "").strip().split("\n\n")[0].replace("\n", " ")
            if best.name and doc.startswith(best.name + "("):
                doc = ""
            return {"full": best.full_name or best.name or "", "text": best.to_string(), "note": doc[:120]}
        except Exception:  # noqa: BLE001 jedi падает на редком коде, а подсказка не стоит ошибки
            return None
