"""Редактор кода: подсветка, автодополнение, мультикурсор и команды со строками."""
import builtins
import html
import keyword
import re

from PyQt6.Qsci import QsciAPIs, QsciLexerCPP, QsciLexerHTML, QsciLexerJavaScript, QsciLexerPython, QsciScintilla
from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QToolTip

from theme import code_family

SCI_MARKERSETFORE = 2041
SCI_MARKERSETBACK = 2042
SCI_GETCHARAT = 2007
SCI_GETCURRENTPOS = 2008
SCI_GETLINEENDPOSITION = 2136
SCI_SCROLLCARET = 2169
SCI_EMPTYUNDOBUFFER = 2175
SCI_SETSEARCHFLAGS = 2198
SCI_TAB = 2327
SCI_BACKTAB = 2328
SCI_LINEDELETE = 2338
SCI_GETZOOM = 2374
SCI_SETZOOM = 2373
SCI_LINEDUPLICATE = 2404
SCI_SETMULTIPLESELECTION = 2563
SCI_SETADDITIONALSELECTIONTYPING = 2565
SCI_GETSELECTIONS = 2570
SCI_GETSELECTIONNSTART = 2585
SCI_GETSELECTIONNEND = 2587
SCI_SETADDITIONALSELBACK = 2601
SCI_SETADDITIONALCARETFORE = 2604
SCI_SETMULTIPASTE = 2614
SCI_MOVESELECTEDLINESUP = 2620
SCI_MOVESELECTEDLINESDOWN = 2621
SCI_MULTIPLESELECTADDNEXT = 2688
SCI_TARGETWHOLEDOCUMENT = 2690
SCI_SETKEYWORDS = 4005
SCI_SETEXTRAASCENT = 2525
SCI_SETEXTRADESCENT = 2527
SCI_INDICSETSTYLE = 2080
SCI_INDICSETFORE = 2082
SCI_STYLESETSIZE = 2055
SCI_STYLESETFONT = 2056
SCI_CALLTIPSHOW = 2200
SCI_CALLTIPCANCEL = 2201
SCI_CALLTIPACTIVE = 2202
SCI_CALLTIPSETHLT = 2204
SCI_CALLTIPUSESTYLE = 2212
SCI_CALLTIPSETPOSITION = 2213
SCI_SETMOUSEDWELLTIME = 2264
SCI_SETINDICATORCURRENT = 2500
SCI_INDICATORFILLRANGE = 2504
SCI_INDICATORCLEARRANGE = 2505
INDIC_SQUIGGLEPIXMAP = 13
STYLE_CALLTIP = 38
PROBLEM_INDICATOR = 8
SCFIND_MATCHCASE = 4

RUST_KEYWORDS = (
    "as break const continue crate dyn else enum extern false fn for if impl in let loop match mod move mut "
    "pub ref return self Self static struct super trait true type unsafe use where while async await"
)
RUST_TYPES = "i8 i16 i32 i64 i128 isize u8 u16 u32 u64 u128 usize f32 f64 bool char str String Vec Option Result Some None Ok Err Box"
PY_WORDS = sorted(set(keyword.kwlist) | {n for n in dir(builtins) if not n.startswith("_")})
JS_WORDS = (
    "await async break case catch class const continue default delete do else export extends false finally for "
    "function if import in instanceof let new null of return static super switch this throw true try typeof "
    "undefined var void while yield console log Array Object String Number Boolean Math JSON Promise Map Set "
    "document window addEventListener querySelector getElementById require module exports"
).split()
RUST_WORDS = (RUST_KEYWORDS + " " + RUST_TYPES + " println! print! format! vec! panic! assert! assert_eq! eprintln! macroquad").split()
HTML_WORDS = (
    "html head body title meta link style script div span section article header footer nav main aside "
    "h1 h2 h3 h4 h5 h6 p a img ul ol li table tr td th form input button select option textarea label "
    "class id href src alt type name value placeholder"
).split()

REGION_STARTS = ("▼ ИЗМЕНЯЙ ТОЛЬКО ЗДЕСЬ", "▼ CHANGE ONLY HERE", "▼ ТАНҲО ДАР ИН ҶО ИВАЗ КУН")
REGION_END = "▲"
COMMENT_PREFIX = re.compile(r"^\s*(#|//)\s*")
REGION_MARKER = 1

OPENERS = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}
CLOSERS = set(OPENERS.values())


def _style_kind(name: str) -> str:
    name = name.lower()
    if "comment" in name:
        return "comment"
    if any(w in name for w in ("string", "character", "quoted", "regular expression", "value")):
        return "string"
    if "number" in name:
        return "number"
    if any(w in name for w in ("function", "class", "decorator", "method", "attribute")):
        return "def"
    if any(w in name for w in ("keyword", "tag")):
        return "keyword"
    if "operator" in name:
        return "op"
    return "fg"


class CodeEditor(QsciScintilla):
    edited = pyqtSignal()
    position_changed = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._loading = False
        self._lexer = None
        self._apis = None
        self.language = ""
        self.locked = False
        self.colors = None
        self.problems = []
        self._tip_text = b""

        self.setUtf8(True)
        self.setEolMode(QsciScintilla.EolMode.EolUnix)
        self.setIndentationsUseTabs(False)
        self.setTabWidth(4)
        self.setIndentationWidth(4)
        self.setTabIndents(True)
        self.setBackspaceUnindents(True)
        self.setAutoIndent(True)
        self.setIndentationGuides(True)
        self.setBraceMatching(QsciScintilla.BraceMatch.SloppyBraceMatch)
        self.setCaretLineVisible(True)
        self.setCaretWidth(2)
        self.setScrollWidth(1)
        self.setScrollWidthTracking(True)
        self.setFrameShape(self.Shape.NoFrame)
        self.setMarginType(0, QsciScintilla.MarginType.NumberMargin)
        self.setMarginWidth(1, 0)
        self.setFolding(QsciScintilla.FoldStyle.BoxedTreeFoldStyle, 2)
        self.setAutoCompletionSource(QsciScintilla.AutoCompletionSource.AcsAll)
        self.setAutoCompletionThreshold(2)
        self.setAutoCompletionCaseSensitivity(False)
        self.setAutoCompletionUseSingle(QsciScintilla.AutoCompletionUseSingle.AcusNever)

        self.SendScintilla(SCI_SETMULTIPLESELECTION, 1)
        self.SendScintilla(SCI_SETADDITIONALSELECTIONTYPING, 1)
        self.SendScintilla(SCI_SETMULTIPASTE, 1)
        self.setCallTipsStyle(QsciScintilla.CallTipsStyle.CallTipsNone)  # подсказки показывает assist.py
        self.SendScintilla(SCI_SETMOUSEDWELLTIME, 350)
        self.SCN_DWELLSTART.connect(self._dwell)
        self.SCN_DWELLEND.connect(lambda *_: QToolTip.hideText())

        self.SendScintilla(SCI_SETEXTRAASCENT, 2)
        self.SendScintilla(SCI_SETEXTRADESCENT, 2)
        self.markerDefine(QsciScintilla.MarkerSymbol.Background, REGION_MARKER)
        self._free_shortcuts()

        self.textChanged.connect(self._text_changed)
        self.cursorPositionChanged.connect(self._cursor_moved)
        self.selectionChanged.connect(self._apply_lock)
        self.linesChanged.connect(self._fit_margin)
        self.SCN_ZOOM.connect(self._fit_margin)
        self._fit_margin()

    def _free_shortcuts(self) -> None:
        """Освобождает сочетания, которые Scintilla занимает своими редкими командами."""
        keys = [Qt.Key.Key_D, Qt.Key.Key_L, Qt.Key.Key_T, Qt.Key.Key_U, Qt.Key.Key_K, Qt.Key.Key_Slash,
                Qt.Key.Key_BracketLeft, Qt.Key.Key_BracketRight, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Backslash]
        ctrl, shift = Qt.KeyboardModifier.ControlModifier.value, Qt.KeyboardModifier.ShiftModifier.value
        taken = set()
        for k in keys:
            taken.add(ctrl | k.value)
            taken.add(ctrl | shift | k.value)
        taken.add(shift | Qt.KeyboardModifier.AltModifier.value | Qt.Key.Key_Down.value)
        for cmd in self.standardCommands().commands():
            if cmd.key() in taken:
                cmd.setKey(0)
            if cmd.alternateKey() in taken:
                cmd.setAlternateKey(0)

    # --- внешний вид ---

    def apply_theme(self, c: dict) -> None:
        self.colors = c
        q = QColor
        font = QFont(code_family(), 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.setFont(font)
        self.setPaper(q(c["code"]))
        self.setColor(q(c["fg"]))
        self._install_lexer()
        self.setCaretForegroundColor(q(c["fg"]))
        self.setCaretLineBackgroundColor(q(c["panel2"]))
        self.setSelectionBackgroundColor(q(c["select"]))
        self.resetSelectionForegroundColor()
        self.SendScintilla(SCI_SETADDITIONALSELBACK, self._bgr(c["select"]))
        self.SendScintilla(SCI_SETADDITIONALCARETFORE, self._bgr(c["lime"]))
        self.setMarginsFont(font)
        self.setMarginsBackgroundColor(q(c["code"]))
        self.setMarginsForegroundColor(q(c["faint"]))
        self.setFoldMarginColors(q(c["code"]), q(c["code"]))
        for n in range(25, 32):
            self.SendScintilla(SCI_MARKERSETFORE, n, self._bgr(c["code"]))
            self.SendScintilla(SCI_MARKERSETBACK, n, self._bgr(c["faint"]))
        self.setMarkerBackgroundColor(q(c["limebg"]), REGION_MARKER)
        self.setMatchedBraceBackgroundColor(q(c["line3"]))
        self.setMatchedBraceForegroundColor(q(c["fg"]))
        self.setUnmatchedBraceForegroundColor(q(c["rose"]))
        self.setUnmatchedBraceBackgroundColor(q(c["code"]))
        self.setIndentationGuidesForegroundColor(q(c["line"]))
        self.setIndentationGuidesBackgroundColor(q(c["code"]))
        self.SendScintilla(SCI_INDICSETSTYLE, PROBLEM_INDICATOR, INDIC_SQUIGGLEPIXMAP)
        self.SendScintilla(SCI_INDICSETFORE, PROBLEM_INDICATOR, self._bgr(c["rose"]))
        self.SendScintilla(SCI_STYLESETFONT, STYLE_CALLTIP, code_family().encode())
        self.SendScintilla(SCI_STYLESETSIZE, STYLE_CALLTIP, 10)
        self.SendScintilla(SCI_CALLTIPUSESTYLE, 0)
        self.SendScintilla(SCI_CALLTIPSETPOSITION, 1)  # над строкой: снизу открывается список слов
        self.setCallTipsBackgroundColor(q(c["panel2"]))
        self.setCallTipsForegroundColor(q(c["fg"]))
        self.setCallTipsHighlightColor(q(c["keyword"]))
        self._fit_margin()

    @staticmethod
    def _bgr(color: str) -> int:
        q = QColor(color)
        return q.red() | (q.green() << 8) | (q.blue() << 16)

    def _fit_margin(self, *_):
        self.setMarginWidth(0, "0" * max(3, len(str(self.lines())) + 1))

    def set_language(self, language: str) -> None:
        if language != self.language:
            self.language = language
            if self.colors:  # setLexer сбрасывает цвета полей и скобок
                self.apply_theme(self.colors)

    def _family(self) -> str:
        if self.language in ("rust", "macroquad"):
            return "rust"
        if self.language == "html":
            return "html"
        if self.language in ("javascript", "node", "dom"):
            return "js"
        return "python"

    def _install_lexer(self) -> None:
        if not self.colors:
            return
        family = self._family()
        lexer = {"python": QsciLexerPython, "rust": QsciLexerCPP, "html": QsciLexerHTML, "js": QsciLexerJavaScript}[family](self)
        c = self.colors
        font = QFont(code_family(), 11)
        font.setStyleHint(QFont.StyleHint.Monospace)
        lexer.setDefaultPaper(QColor(c["code"]))
        lexer.setDefaultColor(QColor(c["fg"]))
        lexer.setDefaultFont(font)
        for style in range(128):
            name = lexer.description(style)
            if name:
                lexer.setPaper(QColor(c["code"]), style)
                lexer.setFont(font, style)
                lexer.setColor(QColor(c[_style_kind(name)]), style)
        words = {"python": PY_WORDS, "rust": RUST_WORDS, "html": HTML_WORDS, "js": JS_WORDS}[family]
        apis = QsciAPIs(lexer)
        for word in words:
            apis.add(word)
        apis.prepare()
        old = self._lexer
        self._lexer, self._apis = lexer, apis
        self.setLexer(lexer)
        if family == "rust":
            self.SendScintilla(SCI_SETKEYWORDS, 0, RUST_KEYWORDS.encode())
            self.SendScintilla(SCI_SETKEYWORDS, 1, RUST_TYPES.encode())
        if old is not None:
            old.deleteLater()

    # --- содержимое ---

    def load(self, text: str, fresh: bool) -> None:
        self._loading = True
        line, col = self.getCursorPosition()
        top = self.firstVisibleLine()
        self.setReadOnly(False)
        self.setText(text)
        if fresh:
            self.SendScintilla(SCI_EMPTYUNDOBUFFER)
            self.setCursorPosition(0, 0)
        else:
            self.setCursorPosition(min(line, self.lines() - 1), col)
            self.setFirstVisibleLine(top)
        self._loading = False
        self._mark_region(place_cursor=fresh)
        self._apply_lock()

    def replace_all_text(self, text: str) -> None:
        """Заменить весь текст так, чтобы это можно было отменить."""
        self.setReadOnly(False)
        self.setText(text)
        self._mark_region(place_cursor=True)
        self._apply_lock()

    def _text_changed(self) -> None:
        if not self._loading:
            if self.locked:
                self._mark_region()
            self.edited.emit()

    def _cursor_moved(self, line: int, col: int) -> None:
        self.position_changed.emit(line, col)
        self._apply_lock()

    # --- красная линия и подсказка параметров ---

    def set_problems(self, problems: list) -> None:
        self.problems = []
        self.SendScintilla(SCI_SETINDICATORCURRENT, PROBLEM_INDICATOR)
        self.SendScintilla(SCI_INDICATORCLEARRANGE, 0, self.length())
        for p in problems:
            line = min(p.line, self.lines() - 1)
            size = len(self.text(line).rstrip("\r\n"))
            col, end = p.col, p.end
            if col >= size:  # ошибка в конце строки: линия под последним символом
                col, end = max(size - 1, 0), size
            end = min(max(end, col + 1), size)
            self.problems.append((line, col, max(end, col + 1), p))
            if size:
                start = self.positionFromLineIndex(line, col)
                self.SendScintilla(SCI_INDICATORFILLRANGE, start, self.positionFromLineIndex(line, end) - start)

    def go_to_problem(self, problem) -> None:
        self.setCursorPosition(min(problem.line, self.lines() - 1), problem.col)
        self.ensureLineVisible(problem.line)
        self.setFocus()

    def _dwell(self, position: int, x: int, y: int) -> None:
        if position < 0:
            return
        line, index = self.lineIndexFromPosition(position)
        found = next((p for n, col, end, p in self.problems if n == line and col <= index < end), None)
        if not found:
            return
        tip = html.escape(found.message)
        if found.example:
            tip += f'<br><span style="font-family:\'{code_family()}\';">{html.escape(found.example)}</span>'
        QToolTip.showText(self.viewport().mapToGlobal(QPoint(x, y + 18)), tip, self.viewport())

    def show_call_tip(self, offset: int, text: str, start: int, stop: int) -> None:
        before = self.text()[:offset]
        line = before.count("\n")
        position = self.positionFromLineIndex(line, offset - (before.rfind("\n") + 1))
        data = text.encode("utf-8")
        if bytes(data) != self._tip_text or not self.SendScintilla(SCI_CALLTIPACTIVE):
            self._tip_text = bytes(data)
            self.SendScintilla(SCI_CALLTIPSHOW, position, data)
        self.SendScintilla(SCI_CALLTIPSETHLT, max(start, 0), max(stop, 0))

    def hide_call_tip(self) -> None:
        self._tip_text = b""
        if self.SendScintilla(SCI_CALLTIPACTIVE):
            self.SendScintilla(SCI_CALLTIPCANCEL)

    def get_zoom(self) -> int:
        return int(self.SendScintilla(SCI_GETZOOM))

    def set_zoom(self, value: int) -> None:
        self.SendScintilla(SCI_SETZOOM, value)

    # --- защищённые строки в задачах-шаблонах ---

    def set_locked(self, locked: bool) -> None:
        self.locked = locked
        self._mark_region(place_cursor=locked)
        self._apply_lock()

    def _region(self):
        """Строки, которые можно менять: (первая, последняя)."""
        start = None
        for n in range(self.lines()):
            body = COMMENT_PREFIX.sub("", self.text(n)).strip()
            if start is None:
                if body.startswith(REGION_STARTS):
                    start = n
            elif body.startswith(REGION_END):
                return start + 1, n - 1
        return None

    def _region_span(self):
        region = self._region()
        if not region or region[1] < region[0]:
            return None
        return self.positionFromLineIndex(region[0], 0), int(self.SendScintilla(SCI_GETLINEENDPOSITION, region[1]))

    def _mark_region(self, place_cursor: bool = False) -> None:
        self.markerDeleteAll(REGION_MARKER)
        if not self.locked:
            return
        region = self._region()
        if not region:
            return
        for n in range(region[0], region[1] + 1):
            self.markerAdd(n, REGION_MARKER)
        if place_cursor and region[1] >= region[0]:
            self.setCursorPosition(region[0], len(self.text(region[0]).rstrip("\r\n")))
            self.ensureLineVisible(region[0])

    def _apply_lock(self) -> None:
        if not self.locked:
            if self.isReadOnly():
                self.setReadOnly(False)
            return
        span = self._region_span()
        inside = span is not None and all(
            span[0] <= self.SendScintilla(SCI_GETSELECTIONNSTART, i) and self.SendScintilla(SCI_GETSELECTIONNEND, i) <= span[1]
            for i in range(self.SendScintilla(SCI_GETSELECTIONS))
        )
        if self.isReadOnly() == inside:
            self.setReadOnly(not inside)

    def _guard_region(self, event) -> bool:
        """Backspace и Delete на границе разрешённых строк стёрли бы защищённый текст."""
        if not self.locked or self.isReadOnly() or self.hasSelectedText():
            return False
        span = self._region_span()
        if not span:
            return False
        pos = int(self.SendScintilla(SCI_GETCURRENTPOS))
        return (event.key() == Qt.Key.Key_Backspace and pos == span[0]) or (event.key() == Qt.Key.Key_Delete and pos == span[1])

    # --- ввод ---

    def _char(self, pos: int) -> str:
        if pos < 0 or pos >= self.length():
            return ""
        return chr(int(self.SendScintilla(SCI_GETCHARAT, pos)) & 0xFF)

    def _single(self) -> bool:
        return int(self.SendScintilla(SCI_GETSELECTIONS)) == 1

    def _handle_pairs(self, event) -> bool:
        if self.isReadOnly() or not self._single():
            return False
        mods = event.modifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            return False
        pos = int(self.SendScintilla(SCI_GETCURRENTPOS))
        before, after = self._char(pos - 1), self._char(pos)
        key = event.key()
        selected = self.hasSelectedText()

        if key == Qt.Key.Key_Backspace and not selected and before in OPENERS and OPENERS[before] == after:
            line, col = self.getCursorPosition()
            self.beginUndoAction()
            self.setSelection(line, col - 1, line, col + 1)
            self.removeSelectedText()
            self.endUndoAction()
            return True

        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not selected and not self.isListActive() and before + after in ("()", "[]", "{}"):
            line, col = self.getCursorPosition()
            indent = self.indentation(line)
            self.beginUndoAction()
            self.insert("\n" + " " * (indent + 4) + "\n" + " " * indent)
            self.endUndoAction()
            self.setCursorPosition(line + 1, indent + 4)
            return True

        text = event.text()
        if len(text) != 1:
            return False
        if text in CLOSERS and text == after and not selected:
            line, col = self.getCursorPosition()
            self.setCursorPosition(line, col + 1)
            return True
        if text not in OPENERS:
            return False
        closer = OPENERS[text]
        if selected:
            inner = self.selectedText()
            l1, c1, l2, c2 = self.getSelection()
            self.beginUndoAction()
            self.replaceSelectedText(text + inner + closer)
            self.endUndoAction()
            self.setSelection(l1, c1 + 1, l2, c2 + (1 if l1 == l2 else 0))
            return True
        if text == closer:  # кавычка: не внутри слова и не третья подряд
            if before.isalnum() or before == text or after.isalnum():
                return False
        elif after and not after.isspace() and after not in CLOSERS and after not in ",;:":
            return False
        line, col = self.getCursorPosition()
        self.beginUndoAction()
        self.insert(text + closer)
        self.endUndoAction()
        self.setCursorPosition(line, col + 1)
        return True

    def keyPressEvent(self, event) -> None:
        if self._guard_region(event) or self._handle_pairs(event):
            return
        super().keyPressEvent(event)

    # --- команды ---

    def add_next_occurrence(self) -> None:
        self.SendScintilla(SCI_SETSEARCHFLAGS, SCFIND_MATCHCASE)
        self.SendScintilla(SCI_TARGETWHOLEDOCUMENT)
        self.SendScintilla(SCI_MULTIPLESELECTADDNEXT)
        self.SendScintilla(SCI_SCROLLCARET)

    def select_line(self) -> None:
        l1, _, l2, c2 = self.getSelection()
        if l1 < 0:
            l1, _ = self.getCursorPosition()
            l2 = l1
        target = l2 + 1  # повторное нажатие расширяет выделение на следующую строку
        if target >= self.lines():
            self.setSelection(l1, 0, self.lines() - 1, len(self.text(self.lines() - 1)))
        else:
            self.setSelection(l1, 0, target, 0)

    def _selected_lines(self):
        l1, _, l2, c2 = self.getSelection()
        if l1 < 0:
            line, _ = self.getCursorPosition()
            return line, line
        if c2 == 0 and l2 > l1:
            l2 -= 1
        return l1, l2

    def toggle_comment(self) -> None:
        if self.isReadOnly():
            return
        family = self._family()
        opener, closer = {"python": ("# ", ""), "html": ("<!-- ", " -->")}.get(family, ("// ", ""))
        had_selection = self.hasSelectedText()
        cur_line, cur_col = self.getCursorPosition()
        first, last = self._selected_lines()
        lines = [(n, self.text(n).rstrip("\r\n")) for n in range(first, last + 1)]
        solid = [(n, s) for n, s in lines if s.strip()]
        if not solid:
            return
        token, end_token = opener.strip(), closer.strip()
        remove = all(s.strip().startswith(token) and (not end_token or s.strip().endswith(end_token)) for _, s in solid)
        indent = min(len(s) - len(s.lstrip()) for _, s in solid)
        self.beginUndoAction()
        delta = 0
        for n, s in solid:
            if remove:
                body = s.strip()[len(token):]
                if end_token:
                    body = body[: -len(end_token)]
                body = body.removeprefix(" ")
                if end_token:
                    body = body.removesuffix(" ")
                lead = s[: len(s) - len(s.lstrip())]
                new = lead + body
            else:
                new = s[:indent] + opener + s[indent:] + closer
            if n == cur_line:
                delta = len(new) - len(s)
            self.setSelection(n, 0, n, len(s))
            self.replaceSelectedText(new)
        self.endUndoAction()
        if had_selection:
            if last + 1 < self.lines():
                self.setSelection(first, 0, last + 1, 0)
            else:
                self.setSelection(first, 0, last, len(self.text(last)))
        else:
            self.setCursorPosition(cur_line, max(0, cur_col + delta))

    def _edit_lines(self, message: int) -> None:
        if not self.isReadOnly():
            self.SendScintilla(message)

    def duplicate_line(self) -> None:
        self._edit_lines(SCI_LINEDUPLICATE)
        if not self.isReadOnly():
            line, col = self.getCursorPosition()
            self.setCursorPosition(line + 1, col)

    def move_up(self) -> None:
        if not self.locked:
            self._edit_lines(SCI_MOVESELECTEDLINESUP)

    def move_down(self) -> None:
        if not self.locked:
            self._edit_lines(SCI_MOVESELECTEDLINESDOWN)

    def delete_line(self) -> None:
        if not self.locked:
            self._edit_lines(SCI_LINEDELETE)

    def indent_lines(self) -> None:
        self._change_indent(4)

    def outdent_lines(self) -> None:
        self._change_indent(-4)

    def _change_indent(self, step: int) -> None:
        if self.isReadOnly():
            return
        first, last = self._selected_lines()
        self.beginUndoAction()
        for n in range(first, last + 1):
            if self.text(n).strip():
                self.setIndentation(n, max(0, self.indentation(n) + step))
        self.endUndoAction()

    def show_completion(self) -> None:
        self.autoCompleteFromAll()

    def go_to_line(self, line: int) -> None:
        line = max(0, min(line, self.lines() - 1))
        self.setCursorPosition(line, 0)
        self.ensureLineVisible(line)
        self.setFocus()
