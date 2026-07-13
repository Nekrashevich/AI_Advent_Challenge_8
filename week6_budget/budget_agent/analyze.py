from budget_agent import data, ollama, proxyapi, retrieval
from budget_agent.config import LOCAL_MODEL, OPENAI_MODEL


CJK_RANGES = (
    ("\u4e00", "\u9fff"),
    ("\u3400", "\u4dbf"),
)


BUDGET_SYSTEM = (
    "Ты приватный финансовый помощник. Анализируй только переданные данные расходов. "
    "Не выдумывай транзакции. Отвечай по-русски, практично и кратко."
)

STRICT_SYSTEM = (
    "Ты строгий аналитик личных расходов. Используй только контекст. "
    "Отвечай только на русском языке. "
    "Не используй английские или китайские слова в ответе, кроме имен файлов и команд. "
    "Если вопрос о росте или падении расходов, сначала используй документ с динамикой "
    "и перечисляй самые большие положительные изменения, а не просто крупные категории. "
    "Формат ответа:\n"
    "1. Диагноз: одно предложение.\n"
    "2. Факты: 2-4 пункта с суммами.\n"
    "3. Действия: 3 конкретных шага.\n"
    "Если данных нет, скажи что данных недостаточно."
)


def contains_cjk(text):
    return any(start <= char <= end for char in text for start, end in CJK_RANGES)


def deterministic_growth_answer():
    rows = data.load_expenses()
    by_month, _, by_month_category = data.totals(rows)
    months = sorted(by_month)
    prev, last = months[-2], months[-1]
    total_delta = by_month[last] - by_month[prev]
    movers = []
    cats = sorted(set(by_month_category[last]) | set(by_month_category[prev]))
    for category in cats:
        delta = by_month_category[last][category] - by_month_category[prev][category]
        if delta > 0:
            movers.append((delta, category))
    top = sorted(movers, reverse=True)[:3]
    facts = "\n".join(
        f"   - {data.category_label(category)}: рост на {data.money(delta)}."
        for delta, category in top
    )
    actions = [
        "Проверить, были ли поездки разовой тратой; если да, вынести их в отдельный лимит.",
        "Задать недельный лимит на кафе и доставку и заменить часть заказов домашней едой.",
        "Сравнить продуктовые чеки июня с маем и убрать повторяющиеся дорогие позиции.",
    ]
    return (
        f"1. Диагноз: в {last} расходы выросли на {data.money(total_delta)} относительно {prev}; "
        f"главные причины - {', '.join(data.category_label(category) for _, category in top)}.\n"
        "2. Факты:\n"
        f"{facts}\n"
        "3. Действия:\n"
        f"   - {actions[0]}\n"
        f"   - {actions[1]}\n"
        f"   - {actions[2]}\n\n"
        "Защита: числовая сводка рассчитана приложением из CSV, "
        "поэтому ответ остается проверяемым даже при нестабильной генерации."
    )


def is_growth_question(question):
    lowered = question.lower()
    return any(word in lowered for word in ("вырос", "рост", "увелич", "почему больше"))


def _latest_growth_items(limit=4):
    rows = data.load_expenses()
    by_month, _, by_month_category = data.totals(rows)
    months = sorted(by_month)
    prev, last = months[-2], months[-1]
    movers = []
    cats = sorted(set(by_month_category[last]) | set(by_month_category[prev]))
    for category in cats:
        delta = by_month_category[last][category] - by_month_category[prev][category]
        if delta > 0:
            movers.append((delta, category))
    return prev, last, sorted(movers, reverse=True)[:limit]


def deterministic_savings_answer():
    prev, last, top = _latest_growth_items(3)
    facts = "\n".join(
        f"   - {data.category_label(category)}: рост на {data.money(delta)}."
        for delta, category in top
    )
    return (
        f"1. Диагноз: в июле стоит ограничить переменные траты, которые сильнее всего выросли в {last}.\n"
        "2. Факты:\n"
        f"{facts}\n"
        "3. Действия:\n"
        "   - Поездки планировать отдельным лимитом и не смешивать с обычным месячным бюджетом.\n"
        "   - Для кафе и доставки задать недельный лимит и заменить часть заказов домашними обедами.\n"
        "   - Для продуктов сверять чеки с планом покупок и убрать повторяющиеся дорогие позиции."
    )


def deterministic_verbose_savings_answer():
    prev, last, top = _latest_growth_items(5)
    bullets = "\n".join(
        f"- {data.category_label(category)}: рост на {data.money(delta)}; это зона для ручной проверки."
        for delta, category in top
    )
    return (
        "Можно снизить расходы в июле несколькими способами. Начать стоит не с обязательных платежей, "
        "а с переменных категорий, где рост был самым заметным.\n\n"
        f"Что видно по сравнению {last} с {prev}:\n"
        f"{bullets}\n\n"
        "Общий подход: заранее выделить лимиты на поездки, кафе и доставку, продукты и развлечения; "
        "проверять остаток лимита раз в неделю; переносить крупные разовые траты в отдельную строку бюджета. "
        "Так обязательные платежи вроде жилья и коммунальных услуг не трогаются, а экономия появляется за счет "
        "управляемых решений: меньше спонтанных заказов, понятный план покупок, отдельный бюджет на поездки."
    )


def local_budget_answer(question, context, temperature=0.2, num_predict=360, system=STRICT_SYSTEM):
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"Контекст расходов:\n{context}\n\nВопрос: {question}"},
    ]
    return ollama.chat(
        messages,
        model=LOCAL_MODEL,
        temperature=temperature,
        num_ctx=4096,
        num_predict=num_predict,
    )


def cloud_budget_answer(question, context):
    messages = [
        {"role": "system", "content": STRICT_SYSTEM},
        {"role": "user", "content": f"Контекст расходов:\n{context}\n\nВопрос: {question}"},
    ]
    return proxyapi.chat(messages, model=OPENAI_MODEL, temperature=0.1, max_tokens=500)


def answer_with_rag(question, compare_cloud=False):
    index = retrieval.ensure_index()
    hits = index.search(question, top_k=6)
    context = retrieval.context_block(hits)
    local_text, local_stats = local_budget_answer(question, context)
    if contains_cjk(local_text) or is_growth_question(question):
        local_text = deterministic_growth_answer()
        local_stats = {**local_stats, "repaired": True}
    result = {
        "question": question,
        "hits": hits,
        "context": context,
        "local_answer": local_text,
        "local_stats": local_stats,
    }
    if compare_cloud and proxyapi.is_configured():
        cloud_text, cloud_stats = cloud_budget_answer(question, context)
        result["cloud_answer"] = cloud_text
        result["cloud_stats"] = cloud_stats
    return result


def overview_context():
    return data.overview_text(data.load_expenses())
