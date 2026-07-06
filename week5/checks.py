QUESTIONS = [
    {
        "question": "Что такое JavaScript и где он выполняется в браузере?",
        "expectation": "JavaScript — язык программирования для добавления интерактивности на веб-страницы; выполняется в браузере и взаимодействует с HTML/CSS через Web APIs.",
        "expected_sources": ["what_is_javascript"],
    },
    {
        "question": "Чем let и const отличаются при объявлении переменных?",
        "expectation": "let используется для переменных, значение которых можно менять; const — для значений, которые нельзя переassignить после объявления.",
        "expected_sources": ["variables"],
    },
    {
        "question": "Когда в JavaScript используют условные конструкции?",
        "expectation": "Условные конструкции позволяют выполнять разные ветки кода в зависимости от результата проверки.",
        "expected_sources": ["conditionals"],
    },
    {
        "question": "Какие виды циклов описывает MDN и зачем нужны циклы?",
        "expectation": "Циклы повторяют действия; MDN описывает конструкции вроде for, while и do...while, а также работу с коллекциями.",
        "expected_sources": ["loops"],
    },
    {
        "question": "Что такое функции и зачем нужны возвращаемые значения?",
        "expectation": "Функции группируют повторяемый код; return value позволяет функции передать результат обратно вызывающему коду.",
        "expected_sources": ["functions", "return_values"],
    },
    {
        "question": "Как работает event bubbling?",
        "expectation": "При всплытии событие сначала обрабатывается на целевом элементе, затем поднимается к родительским элементам.",
        "expected_sources": ["event_bubbling"],
    },
    {
        "question": "Как JavaScript может изменять DOM?",
        "expectation": "Скрипт может выбирать элементы, менять текст, атрибуты, стили, создавать и удалять узлы через DOM API.",
        "expected_sources": ["dom_scripting"],
    },
    {
        "question": "Что такое JSON и как его используют в JavaScript?",
        "expectation": "JSON — текстовый формат представления структурированных данных; JavaScript может преобразовывать JSON в объекты и обратно.",
        "expected_sources": ["json"],
    },
    {
        "question": "Как fetch используется для сетевых запросов?",
        "expectation": "Fetch API делает HTTP-запросы, возвращает Promise и позволяет получать данные, например JSON, без перезагрузки страницы.",
        "expected_sources": ["network_requests"],
    },
    {
        "question": "Как MDN предлагает отлаживать JavaScript?",
        "expectation": "MDN описывает использование консоли, сообщений об ошибках, console.log и отладчика с breakpoint.",
        "expected_sources": ["debugging_javascript", "what_went_wrong"],
    },
]


def sources_hit(expected_sources, answer_sources):
    used = " ".join(s["source"] for s in answer_sources)
    return any(marker in used for marker in expected_sources)
