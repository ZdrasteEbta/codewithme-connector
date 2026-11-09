"""Тексты подсказок на трёх языках сайта и поиск вызова функции под курсором."""
import re
from dataclasses import dataclass

LOCALES = {"ru": 0, "en": 1, "tg": 2}

MESSAGES = {
    # Python
    "colon": ("В конце этой строки нужно двоеточие.", "This line must end with a colon.", "Дар охири ин сатр ду нуқта лозим аст."),
    "compare": ("В условии сравнивают двумя знаками ==, а один знак = записывает значение.", "Conditions compare with ==, a single = stores a value.", "Дар шарт бо == муқоиса мекунанд, як = қимат менависад."),
    "not_closed": ("Скобка {0} не закрыта.", "The bracket {0} is never closed.", "Қавси {0} баста нашудааст."),
    "unmatched": ("Лишняя скобка {0}: перед ней нет открывающей.", "Extra bracket {0}: nothing opens it.", "Қавси {0} зиёдатӣ аст: пеш аз он қавси кушода нест."),
    "wrong_close": ("Открыта скобка {0}, а закрыта {1}. Они должны быть парой.", "Opened with {0} but closed with {1}. They must match.", "Қавси {0} кушода, вале бо {1} баста шудааст. Онҳо бояд ҷуфт бошанд."),
    "string": ("Кавычка не закрыта: текст должен заканчиваться такой же кавычкой.", "The quote is never closed: end the text with the same quote.", "Нохунак баста нашудааст: матн бояд бо ҳамон нохунак анҷом ёбад."),
    "unexpected_indent": ("Лишний отступ: эта строка не должна быть сдвинута.", "Extra indent: this line should not be shifted.", "Фосилаи зиёдатӣ: ин сатр набояд ба рост ҳаракат кунад."),
    "need_indent": ("После двоеточия следующую строку сдвигают на 4 пробела.", "After a colon, shift the next line by 4 spaces.", "Пас аз ду нуқта сатри навбатиро 4 фосила ба рост мегузоранд."),
    "bad_dedent": ("Отступ не совпадает со строками выше. Сделай его таким же, как у блока.", "This indent matches no line above. Make it the same as its block.", "Фосила бо сатрҳои боло мувофиқ нест. Онро мисли блоки худ кун."),
    "tabs": ("Отступы смешаны: табуляция и пробелы. Оставь только пробелы.", "Tabs and spaces are mixed. Use spaces only.", "Табулятсия ва фосила омехта шудаанд. Танҳо фосила гузор."),
    "print_parens": ("У print нужны скобки.", "print needs brackets.", "Барои print қавс лозим аст."),
    "comma": ("Между значениями нужна запятая.", "A comma is needed between the values.", "Байни қиматҳо вергул лозим аст."),
    "assign": ("Слева от = должно стоять имя переменной.", "The left side of = must be a variable name.", "Аз чапи = бояд номи тағйирёбанда бошад."),
    "bad_number": ("Число и буквы написаны слитно. Имя не может начинаться с цифры.", "A number runs into letters. A name cannot start with a digit.", "Рақам ва ҳарфҳо якҷо навишта шудаанд. Ном аз рақам сар намешавад."),
    "leading_zero": ("Целое число не пишут с нуля в начале.", "Whole numbers are not written with a leading zero.", "Адади бутунро бо сифр дар аввал наменависанд."),
    "try": ("После блока try нужен except или finally.", "A try block needs except or finally after it.", "Пас аз блоки try бояд except ё finally бошад."),
    "bad_char": ("Символ {0} нельзя писать в коде. Часто это русская буква или кавычка-ёлочка.", "The character {0} is not allowed in code. It is often a non-Latin letter or a curly quote.", "Аломати {0}-ро дар код навиштан мумкин нест. Аксар вақт ин ҳарфи русӣ ё нохунаки хоса аст."),
    "fstring": ("Ошибка внутри f-строки: проверь фигурные скобки { }.", "Error inside the f-string: check the { } brackets.", "Хато дар дохили f-сатр: қавсҳои { }-ро санҷ."),
    "def_parens": ("После имени функции нужны скобки.", "A function name must be followed by brackets.", "Пас аз номи функсия қавс лозим аст."),
    "syntax": ("Python не понимает эту строку. Проверь скобки, кавычки и двоеточие.", "Python cannot read this line. Check the brackets, quotes and colon.", "Python ин сатрро намефаҳмад. Қавсҳо, нохунакҳо ва ду нуқтаро санҷ."),
    "typo_keyword": ("Python не знает слова {0}. Может быть, нужно {1}?", "Python does not know the word {0}. Did you mean {1}?", "Python калимаи {0}-ро намедонад. Шояд {1} лозим аст?"),
    "undefined": ("Имя {0} нигде не задано. Сначала присвой ему значение.", "The name {0} is not defined. Give it a value first.", "Номи {0} муайян нашудааст. Аввал ба он қимат деҳ."),
    "undefined_maybe": ("Имя {0} нигде не задано. Может быть, нужно {1}?", "The name {0} is not defined. Did you mean {1}?", "Номи {0} муайян нашудааст. Шояд {1} лозим аст?"),
    "before_assign": ("Переменную {0} используют раньше, чем она получает значение.", "The variable {0} is used before it gets a value.", "Тағйирёбандаи {0} пеш аз гирифтани қимат истифода шудааст."),
    "return_outside": ("return можно писать только внутри функции.", "return is only allowed inside a function.", "return танҳо дар дохили функсия навишта мешавад."),
    "loop_outside": ("break и continue работают только внутри цикла.", "break and continue only work inside a loop.", "break ва continue танҳо дар дохили давра кор мекунанд."),
    "await_outside": ("await и yield работают только внутри функции.", "await and yield only work inside a function.", "await ва yield танҳо дар дохили функсия кор мекунанд."),
    "duplicate_arg": ("Параметр {0} указан дважды.", "The parameter {0} is listed twice.", "Параметри {0} ду бор навишта шудааст."),
    "not_installed": ("Библиотека {0} не установлена. Нажми «Установить все зависимости».", "The {0} library is not installed. Press “Install all dependencies”.", "Китобхонаи {0} насб нашудааст. «Насби ҳамаи вобастагиҳо»-ро пахш кун."),
    "unknown_module": ("Библиотеки {0} нет в списке известных. Проверь название.", "{0} is not a library this app knows. Check the name.", "Китобхонаи {0} дар рӯйхати маълум нест. Номро санҷ."),
    "unknown_module_maybe": ("Библиотеки {0} нет. Может быть, нужно {1}?", "There is no {0} library. Did you mean {1}?", "Китобхонаи {0} нест. Шояд {1} лозим аст?"),
    # JavaScript
    "js_call": ("Не закрыта скобка вызова или пропущена запятая между значениями.", "A call bracket is not closed, or a comma is missing between the values.", "Қавси даъват баста нашудааст ё вергул байни қиматҳо нест."),
    "js_end": ("Код оборвался: не хватает закрывающей скобки.", "The code ends too early: a closing bracket is missing.", "Код барвақт тамом шуд: қавси баста намерасад."),
    "js_token": ("Здесь не ожидается {0}. Проверь скобки и запятые перед этим местом.", "{0} is not expected here. Check the brackets and commas before it.", "Дар ин ҷо {0} интизор нест. Қавсҳо ва вергулҳои пеш аз онро санҷ."),
    "js_quote": ("Незакрытая кавычка или символ, который нельзя писать в коде.", "An unclosed quote, or a character that is not allowed in code.", "Нохунаки кушода ё аломате, ки дар код мумкин нест."),
    "js_redeclared": ("Переменная {0} уже объявлена. Чтобы поменять её, напиши без let и const.", "The variable {0} is already declared. To change it, write it without let or const.", "Тағйирёбандаи {0} аллакай эълон шудааст. Барои иваз бе let ва const навис."),
    "js_const": ("const сразу требует значение.", "const needs a value right away.", "const бояд дарҳол қимат гирад."),
    "js_assign": ("Слева от = должна стоять переменная.", "The left side of = must be a variable.", "Аз чапи = бояд тағйирёбанда бошад."),
    "js_import": ("Здесь библиотеки подключают через require.", "Load libraries with require here.", "Дар ин ҷо китобхонаҳоро бо require пайваст мекунанд."),
    "js_try": ("После блока try нужен catch или finally.", "A try block needs catch or finally after it.", "Пас аз блоки try бояд catch ё finally бошад."),
    # Rust
    "rs_semicolon": ("В конце этой строки нужна точка с запятой.", "This line must end with a semicolon.", "Дар охири ин сатр нуқтавергул лозим аст."),
    "rs_delimiter": ("Скобка не закрыта или закрыта не той парой.", "A bracket is not closed, or closed by the wrong pair.", "Қавс баста нашудааст ё бо ҷуфти нодуруст баста шудааст."),
    "rs_undefined": ("Имя {0} здесь не задано. Проверь написание или объяви его через let.", "The name {0} does not exist here. Check the spelling or declare it with let.", "Номи {0} дар ин ҷо нест. Навиштаро санҷ ё бо let эълон кун."),
    "rs_function": ("Функции {0} нет. Проверь написание.", "There is no function {0}. Check the spelling.", "Функсияи {0} нест. Навиштаро санҷ."),
    "rs_macro": ("Макроса {0}! нет. Проверь написание.", "There is no macro {0}!. Check the spelling.", "Макроси {0}! нест. Навиштаро санҷ."),
    "rs_types": ("Типы не совпадают.", "The types do not match.", "Навъҳо мувофиқ нестанд."),
    "rs_mut": ("Переменную {0} нельзя менять. Объяви её с mut.", "The variable {0} cannot change. Declare it with mut.", "Тағйирёбандаи {0}-ро иваз кардан мумкин нест. Онро бо mut эълон кун."),
    "rs_moved": ("Значение {0} уже передано в другое место. Передай ссылку &{0} или копию {0}.clone().", "The value {0} has already been moved. Pass a reference &{0} or a copy {0}.clone().", "Қимати {0} аллакай ба ҷои дигар дода шудааст. Истинод &{0} ё нусхаи {0}.clone() деҳ."),
    "rs_crate": ("Такой библиотеки здесь нет: в этом курсе работает только стандартная библиотека Rust.", "This library is not available: this course only has the Rust standard library.", "Ин китобхона дар ин ҷо нест: дар ин курс танҳо китобхонаи стандартии Rust кор мекунад."),
}


def say(locale: str, key: str, *args) -> str:
    return MESSAGES[key][LOCALES.get(locale, 0)].format(*args) if args else MESSAGES[key][LOCALES.get(locale, 0)]


# Как называется пакет для установки по имени в import
PIP_NAMES = {name: name for name in (
    "numpy pandas matplotlib seaborn scipy sympy requests httpx aiohttp flask django fastapi uvicorn starlette pydantic "
    "sqlalchemy pytz tqdm rich colorama click typer pytest openpyxl xlrd pypdf aiogram selenium playwright pygame arcade "
    "pyglet ursina panda3d kivy customtkinter torch torchvision torchaudio tensorflow keras transformers nltk spacy gensim "
    "xgboost lightgbm catboost statsmodels plotly bokeh dash streamlit gradio networkx pyautogui pynput keyboard mouse "
    "psutil pyperclip qrcode faker emoji tabulate termcolor redis pymongo orjson ujson toml attrs websockets tornado "
    "gunicorn pyttsx3 wikipedia openai anthropic imageio moviepy pydub shapely geopandas folium pyarrow polars dask h5py "
    "joblib lxml setuptools six certifi urllib3 chardet markupsafe werkzeug itsdangerous"
).split()}
PIP_NAMES.update({
    "sklearn": "scikit-learn", "skimage": "scikit-image", "cv2": "opencv-python", "PIL": "pillow", "bs4": "beautifulsoup4",
    "jinja2": "jinja2", "yaml": "pyyaml", "dotenv": "python-dotenv", "dateutil": "python-dateutil", "docx": "python-docx",
    "pptx": "python-pptx", "PyPDF2": "pypdf2", "fitz": "pymupdf", "telebot": "pytelegrambotapi", "telegram": "python-telegram-bot",
    "discord": "discord.py", "vk_api": "vk-api", "webdriver_manager": "webdriver-manager", "PySide6": "PySide6-Essentials",
    "PyQt6": "pyqt6", "PyQt5": "pyqt5", "pymysql": "pymysql", "psycopg2": "psycopg2-binary", "serial": "pyserial",
    "Crypto": "pycryptodome", "jwt": "pyjwt", "nacl": "pynacl", "attr": "attrs", "more_itertools": "more-itertools",
    "mpl_toolkits": "matplotlib", "pkg_resources": "setuptools", "websocket": "websocket-client", "gtts": "gtts",
    "speech_recognition": "speechrecognition", "yt_dlp": "yt-dlp", "IPython": "ipython",
})

# Как ставить пакет npm (курс Express написан под пятую версию)
NPM_NAMES = {name: name for name in (
    "lodash axios chalk dotenv cors body-parser morgan uuid dayjs nodemon ws socket.io sqlite3 mongoose bcryptjs jsonwebtoken"
).split()}
NPM_NAMES["express"] = "express@5"

NODE_BUILTINS = frozenset((
    "assert async_hooks buffer child_process cluster console constants crypto dgram diagnostics_channel dns domain events fs "
    "http http2 https inspector module net os path perf_hooks process punycode querystring readline repl stream string_decoder "
    "sys timers tls trace_events tty url util v8 vm wasi worker_threads zlib"
).split())


# --- подписи функций ---

PY_SIGNATURES = {
    "print": ('print(*values, sep=" ", end="\\n")', "Выводит значения на экран.", "Prints values to the screen.", "Қиматҳоро дар экран нишон медиҳад."),
    "input": ('input(prompt="")', "Читает строку, которую ввели. Результат всегда текст.", "Reads a typed line. The result is always text.", "Сатри воридшударо мехонад. Натиҷа ҳамеша матн аст."),
    "len": ("len(obj)", "Количество элементов или символов.", "The number of items or characters.", "Шумораи элементҳо ё аломатҳо."),
    "range": ("range(start=0, stop, step=1)", "Числа от start до stop, не включая stop.", "Numbers from start up to, but not including, stop.", "Рақамҳо аз start то stop, бе худи stop."),
    "int": ("int(value=0, base=10)", "Превращает значение в целое число.", "Converts a value to a whole number.", "Қиматро ба адади бутун табдил медиҳад."),
    "float": ("float(value=0)", "Превращает значение в дробное число.", "Converts a value to a decimal number.", "Қиматро ба адади даҳӣ табдил медиҳад."),
    "str": ('str(value="")', "Превращает значение в текст.", "Converts a value to text.", "Қиматро ба матн табдил медиҳад."),
    "bool": ("bool(value=False)", "Превращает значение в True или False.", "Converts a value to True or False.", "Қиматро ба True ё False табдил медиҳад."),
    "list": ("list(iterable=())", "Создаёт список.", "Creates a list.", "Рӯйхат месозад."),
    "tuple": ("tuple(iterable=())", "Создаёт кортеж.", "Creates a tuple.", "Кортеж месозад."),
    "set": ("set(iterable=())", "Создаёт множество без повторов.", "Creates a set without duplicates.", "Маҷмӯаи бе такрор месозад."),
    "dict": ("dict(**pairs)", "Создаёт словарь.", "Creates a dictionary.", "Луғат месозад."),
    "sum": ("sum(iterable, start=0)", "Сумма всех чисел.", "The total of all numbers.", "Ҷамъи ҳамаи рақамҳо."),
    "min": ("min(*values, key=None)", "Самое маленькое значение.", "The smallest value.", "Қимати хурдтарин."),
    "max": ("max(*values, key=None)", "Самое большое значение.", "The largest value.", "Қимати калонтарин."),
    "abs": ("abs(number)", "Число без знака минус.", "The number without its minus sign.", "Рақам бе аломати минус."),
    "round": ("round(number, ndigits=0)", "Округляет число.", "Rounds a number.", "Рақамро яклухт мекунад."),
    "sorted": ("sorted(iterable, key=None, reverse=False)", "Новый отсортированный список.", "A new sorted list.", "Рӯйхати нави мураттаб."),
    "enumerate": ("enumerate(iterable, start=0)", "Пары: номер и элемент.", "Pairs of index and item.", "Ҷуфтҳо: рақам ва элемент."),
    "zip": ("zip(*iterables)", "Склеивает последовательности попарно.", "Joins sequences pairwise.", "Пайдарпайиҳоро ҷуфт-ҷуфт мепайвандад."),
    "map": ("map(function, iterable)", "Применяет функцию к каждому элементу.", "Applies a function to every item.", "Функсияро ба ҳар элемент татбиқ мекунад."),
    "filter": ("filter(function, iterable)", "Оставляет элементы, для которых функция вернула True.", "Keeps the items where the function returns True.", "Элементҳоеро мегузорад, ки функсия барояшон True додааст."),
    "open": ('open(file, mode="r", encoding=None)', "Открывает файл.", "Opens a file.", "Файлро мекушояд."),
    "isinstance": ("isinstance(obj, class_or_tuple)", "Проверяет тип значения.", "Checks the type of a value.", "Навъи қиматро месанҷад."),
    "type": ("type(obj)", "Узнаёт тип значения.", "Gets the type of a value.", "Навъи қиматро муайян мекунад."),
    "builtins.list.append": ("append(item)", "Добавляет элемент в конец списка.", "Adds an item to the end of the list.", "Элементро ба охири рӯйхат илова мекунад."),
    "builtins.list.insert": ("insert(index, item)", "Вставляет элемент перед позицией index.", "Inserts an item before position index.", "Элементро пеш аз мавқеи index мегузорад."),
    "builtins.list.pop": ("pop(index=-1)", "Удаляет элемент и возвращает его.", "Removes an item and returns it.", "Элементро нест карда бармегардонад."),
    "builtins.list.remove": ("remove(value)", "Удаляет первый элемент с таким значением.", "Removes the first item with this value.", "Аввалин элементи бо ин қиматро нест мекунад."),
    "builtins.list.sort": ("sort(key=None, reverse=False)", "Сортирует сам список.", "Sorts the list in place.", "Худи рӯйхатро мураттаб мекунад."),
    "builtins.str.split": ("split(sep=None, maxsplit=-1)", "Разбивает текст на список слов.", "Splits text into a list of words.", "Матнро ба рӯйхати калимаҳо ҷудо мекунад."),
    "builtins.str.join": ("join(iterable)", "Склеивает список строк через этот текст.", "Joins a list of strings with this text.", "Рӯйхати сатрҳоро бо ин матн мепайвандад."),
    "builtins.str.replace": ("replace(old, new, count=-1)", "Заменяет часть текста.", "Replaces part of the text.", "Қисми матнро иваз мекунад."),
    "builtins.str.strip": ("strip(chars=None)", "Убирает пробелы по краям.", "Removes spaces at both ends.", "Фосилаҳои канорро нест мекунад."),
    "builtins.str.find": ("find(sub, start=0, end=len(s))", "Позиция подстроки или -1.", "The position of a substring, or -1.", "Мавқеи зерсатр ё -1."),
    "builtins.str.startswith": ("startswith(prefix, start=0, end=len(s))", "Проверяет начало текста.", "Checks how the text starts.", "Аввали матнро месанҷад."),
    "builtins.dict.get": ("get(key, default=None)", "Значение по ключу, а если ключа нет, default.", "The value for a key, or default if it is missing.", "Қимат аз рӯи калид ё default, агар калид набошад."),
}

JS_SIGNATURES = {
    "console.log": ("console.log(...values)", "Выводит значения на экран.", "Prints values to the screen.", "Қиматҳоро дар экран нишон медиҳад."),
    "parseInt": ("parseInt(text, radix=10)", "Превращает текст в целое число.", "Converts text to a whole number.", "Матнро ба адади бутун табдил медиҳад."),
    "parseFloat": ("parseFloat(text)", "Превращает текст в дробное число.", "Converts text to a decimal number.", "Матнро ба адади даҳӣ табдил медиҳад."),
    "setTimeout": ("setTimeout(callback, delayMs)", "Вызывает функцию через delayMs миллисекунд.", "Calls a function after delayMs milliseconds.", "Функсияро пас аз delayMs миллисония даъват мекунад."),
    "setInterval": ("setInterval(callback, delayMs)", "Вызывает функцию каждые delayMs миллисекунд.", "Calls a function every delayMs milliseconds.", "Функсияро ҳар delayMs миллисония даъват мекунад."),
    "require": ("require(name)", "Подключает библиотеку.", "Loads a library.", "Китобхонаро пайваст мекунад."),
    "JSON.stringify": ("JSON.stringify(value, replacer, indent)", "Превращает значение в текст JSON.", "Converts a value to JSON text.", "Қиматро ба матни JSON табдил медиҳад."),
    "JSON.parse": ("JSON.parse(text)", "Читает текст JSON.", "Reads JSON text.", "Матни JSON-ро мехонад."),
    "Math.floor": ("Math.floor(x)", "Округляет вниз.", "Rounds down.", "Ба поён яклухт мекунад."),
    "Math.ceil": ("Math.ceil(x)", "Округляет вверх.", "Rounds up.", "Ба боло яклухт мекунад."),
    "Math.round": ("Math.round(x)", "Округляет до целого.", "Rounds to a whole number.", "То адади бутун яклухт мекунад."),
    "Math.max": ("Math.max(...values)", "Самое большое число.", "The largest number.", "Адади калонтарин."),
    "Math.min": ("Math.min(...values)", "Самое маленькое число.", "The smallest number.", "Адади хурдтарин."),
    "document.querySelector": ("document.querySelector(selector)", "Находит первый элемент страницы.", "Finds the first element on the page.", "Аввалин элементи саҳифаро меёбад."),
    "document.createElement": ("document.createElement(tag)", "Создаёт новый элемент.", "Creates a new element.", "Элементи нав месозад."),
    ".addEventListener": ("addEventListener(event, handler)", "Подписывает функцию на событие.", "Runs a function when the event happens.", "Функсияро ба ҳодиса мепайвандад."),
    ".push": ("push(...items)", "Добавляет элементы в конец массива.", "Adds items to the end of the array.", "Элементҳоро ба охири массив илова мекунад."),
    ".map": ("map(callback(item, index))", "Новый массив из результатов функции.", "A new array of the function's results.", "Массиви нав аз натиҷаҳои функсия."),
    ".filter": ("filter(callback(item, index))", "Элементы, для которых функция вернула true.", "The items where the function returns true.", "Элементҳое, ки функсия барояшон true додааст."),
    ".forEach": ("forEach(callback(item, index))", "Вызывает функцию для каждого элемента.", "Calls a function for every item.", "Функсияро барои ҳар элемент даъват мекунад."),
    ".reduce": ("reduce(callback(sum, item), start)", "Сворачивает массив в одно значение.", "Folds an array into one value.", "Массивро ба як қимат ҷамъ мекунад."),
    ".join": ('join(separator=",")', "Склеивает массив в строку.", "Joins an array into a string.", "Массивро ба сатр мепайвандад."),
    ".slice": ("slice(start, end)", "Копия части, end не включается.", "A copy of a part, without end.", "Нусхаи қисм, бе end."),
    ".split": ("split(separator)", "Разбивает строку на массив.", "Splits a string into an array.", "Сатрро ба массив ҷудо мекунад."),
    ".includes": ("includes(value)", "Проверяет, есть ли значение.", "Checks whether the value is present.", "Месанҷад, ки қимат ҳаст ё не."),
}

RS_SIGNATURES = {
    "println!": ('println!("{}", value)', "Выводит строку. Каждое {} заменяется значением.", "Prints a line. Each {} is replaced by a value.", "Сатрро чоп мекунад. Ҳар {} бо қимат иваз мешавад."),
    "print!": ('print!("{}", value)', "Выводит текст без перевода строки.", "Prints text without a line break.", "Матнро бе гузариши сатр чоп мекунад."),
    "format!": ('format!("{}", value)', "Собирает строку по шаблону.", "Builds a string from a template.", "Аз рӯи қолиб сатр месозад."),
    "vec!": ("vec![a, b, c]", "Создаёт вектор.", "Creates a vector.", "Вектор месозад."),
    "String::from": ('String::from("text")', "Создаёт строку String.", "Creates a String.", "String месозад."),
    "Vec::new": ("Vec::new()", "Создаёт пустой вектор.", "Creates an empty vector.", "Вектори холӣ месозад."),
    "Vec::with_capacity": ("Vec::with_capacity(capacity)", "Пустой вектор с запасом места.", "An empty vector with spare room.", "Вектори холӣ бо ҷои захира."),
    ".push": ("push(value)", "Добавляет элемент в конец.", "Adds an item to the end.", "Элементро ба охир илова мекунад."),
    ".push_str": ("push_str(text)", "Дописывает текст к строке.", "Appends text to the string.", "Матнро ба сатр илова мекунад."),
    ".read_line": ("read_line(&mut text)", "Читает строку ввода в text.", "Reads a line of input into text.", "Сатри вурудро ба text мехонад."),
    ".insert": ("insert(key, value)", "Добавляет пару в словарь.", "Adds a pair to the map.", "Ҷуфтро ба луғат илова мекунад."),
    ".get": ("get(key_or_index)", "Возвращает Option со ссылкой на значение.", "Returns an Option with a reference to the value.", "Option бо истинод ба қимат бармегардонад."),
    ".map": ("map(|item| result)", "Меняет каждый элемент итератора.", "Transforms every item of the iterator.", "Ҳар элементи итераторро иваз мекунад."),
    ".filter": ("filter(|item| condition)", "Оставляет подходящие элементы.", "Keeps the matching items.", "Элементҳои мувофиқро мегузорад."),
}

_NOT_CALLS = {"if", "elif", "while", "for", "return", "and", "or", "not", "in", "is", "switch", "catch", "match", "assert", "del", "yield", "await", "with", "lambda", "typeof", "new"}
_DEFINITIONS = {"def", "class", "function", "fn", "struct", "enum", "impl", "trait"}


@dataclass
class Call:
    name: str
    open: int  # место открывающей скобки в тексте
    index: int  # номер аргумента с нуля
    keyword: str


def call_at(text: str, pos: int, family: str):
    """Находит вызов функции, внутри скобок которого стоит курсор."""
    stack = []
    i, end = 0, min(pos, len(text))
    while i < end:
        ch = text[i]
        two = text[i:i + 2]
        if family == "python":
            if ch == "#":
                i = _line_end(text, i)
                continue
            if ch in "\"'":
                i = _skip_python_string(text, i)
                continue
        else:
            if two == "//":
                i = _line_end(text, i)
                continue
            if two == "/*":
                stop = text.find("*/", i + 2)
                i = stop + 2 if stop >= 0 else len(text)
                continue
            if ch == '"' or (family == "js" and ch in "'`"):
                i = _skip_quoted(text, i, ch)
                continue
            if family == "rust" and ch == "'":
                m = re.compile(r"'(\\.|[^\\'])'").match(text, i)
                i = m.end() if m else i + 1
                continue
        if ch in "([{":
            stack.append([ch, i, 0, i + 1])
        elif ch in ")]}":
            if stack:
                stack.pop()
        elif ch == "," and stack:
            stack[-1][2] += 1
            stack[-1][3] = i + 1
        i += 1
    if i > end or not stack or stack[-1][0] != "(":
        return None  # курсор внутри строки, комментария или вне круглых скобок
    _, opened, index, last = stack[-1]
    m = re.search(r"([\w.:!]+)\s*$", text[:opened])
    if not m:
        return None
    name = m.group(1)
    if name in _NOT_CALLS:
        return None
    before = re.search(r"(\w+)\s+$", text[:m.start()])
    if before and before.group(1) in _DEFINITIONS:
        return None
    keyword = re.match(r"\s*(\w+)\s*=(?!=)", text[last:end])
    return Call(name, opened, index, keyword.group(1) if keyword else "")


def _line_end(text, i):
    stop = text.find("\n", i)
    return stop if stop >= 0 else len(text)


def _skip_quoted(text, i, quote):
    i += 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == quote:
            return i + 1
        if text[i] == "\n" and quote != "`":
            return i
        i += 1
    return i + 1  # строка не закрыта до конца текста


def _skip_python_string(text, i):
    quote = text[i]
    if text[i:i + 3] == quote * 3:
        stop = text.find(quote * 3, i + 3)
        return stop + 3 if stop >= 0 else len(text) + 1
    return _skip_quoted(text, i, quote)


def local_signature(family: str, call: Call, text: str, locale: str):
    """Подпись, которую можно найти без анализа типов: (подпись, описание) или None."""
    col = LOCALES.get(locale, 0) + 1
    if family == "python":
        name = re.escape(call.name)
        redefined = re.search(rf"^\s*(?:def|class)\s+{name}\b|^\s*{name}\s*=(?!=)", text, re.M)
        entry = PY_SIGNATURES.get(call.name)
        return (entry[0], entry[col]) if entry and not redefined else None
    table = JS_SIGNATURES if family == "js" else RS_SIGNATURES
    name = call.name.rsplit(".", 1)[-1]
    pattern = (
        rf"function\s+{re.escape(name)}\s*(\([^)]*\))|\b{re.escape(name)}\s*=\s*(?:async\s*)?(\([^)]*\))\s*=>"
        if family == "js" else rf"\bfn\s+{re.escape(name)}\s*(?:<[^>]*>)?\s*(\([^)]*\)(?:\s*->\s*[^{{\n]+)?)"
    )
    own = re.search(pattern, text)
    if own:
        return call.name + (own.group(1) or own.group(2)).strip(), ""
    entry = table.get(call.name) or (table.get("." + name) if "." in call.name else None)
    return (entry[0], entry[col]) if entry else None


def signature_from_jedi(found: dict, locale: str):
    entry = PY_SIGNATURES.get(found["full"])
    if entry:
        return entry[0], entry[LOCALES.get(locale, 0) + 1]
    return found["text"], found["note"]


def _split_signature(signature: str):
    """Разбирает подпись на имя, параметры и хвост (-> тип). Без скобок вернёт None."""
    start = signature.find("(")
    if start < 0:
        return None
    depth, quote, pieces, begin = 0, "", [], start + 1
    for i in range(start, len(signature)):
        ch = signature[i]
        if quote:
            if ch == quote and signature[i - 1] != "\\":
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                tail = signature[begin:i].strip()
                if tail:
                    pieces.append(tail)
                return signature[:start], pieces, signature[i + 1:]
        elif ch == "," and depth == 1:
            pieces.append(signature[begin:i].strip())
            begin = i + 1
    return None


def _short_param(param: str) -> str:
    m = re.match(r"(\*{0,2}\w+)\s*(?::.*?)?(?:\s*=\s*(.*))?$", param, re.S)
    if not m:
        return param
    return f"{m.group(1)}={m.group(2)}" if m.group(2) else m.group(1)


def _active(params, index: int, keyword: str):
    if keyword:
        for i, p in enumerate(params):
            if re.match(rf"\*{{0,2}}{re.escape(keyword)}\b", p):
                return i
        return None
    position = 0
    for i, p in enumerate(params):
        if p == "/":
            continue
        if p == "*" or p.startswith("**"):
            return None
        if p.startswith("*") or p.startswith("..."):
            return i
        if position == index:
            return i
        position += 1
    return None


def render_signature(signature: str, note: str, call: Call):
    """Текст всплывающей подсказки и место текущего параметра в байтах: (текст, начало, конец)."""
    parts = _split_signature(signature)
    if parts is None:
        text = signature + ("\n" + note if note else "")
        return text, -1, -1
    head, params, tail = parts
    active = _active(params, call.index, call.keyword)
    if len(signature) > 100:
        params, tail = [_short_param(p) for p in params], ""
    if len(params) > 9:  # у функций библиотек бывают десятки параметров
        keep = sorted(set(range(5)) | ({active} if active is not None else set()))
        shown, position = [], None
        for i in keep:
            if i == active:
                position = len(shown)
            shown.append(params[i])
        shown.append("…")
        params, active = shown, position

    text, column, start, stop = head + "(", len(head) + 1, -1, -1
    for i, param in enumerate(params):
        if column + len(param) > 88 and i:
            text = text.rstrip() + "\n    "
            column = 4
        if i == active:
            start = len(text.encode())
        text += param
        if i == active:
            stop = len(text.encode())
        if i < len(params) - 1:
            text += ", "
        column = len(text) - (text.rfind("\n") + 1)
    text += ")" + tail
    if note:
        text += "\n" + note
    return text, start, stop
