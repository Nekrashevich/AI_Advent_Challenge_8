from budget_pipeline import support, support_tools
from budget_pipeline.llm import LLMResult


class FakeBridge:
    def call(self, server, name, arguments=None):
        assert server == "support"
        assert name == "get_ticket"
        return support_tools.get_ticket(arguments["ticket_id"])

    def status(self):
        return [{"server": "support", "connected": True, "tools": 3, "error": ""}]


class FakeClient:
    def chat_json(self, messages, **kwargs):
        payload = {
            "diagnosis": "Повторный импорт уже помечен как duplicate.",
            "reply": "Вторая строка исключена из итогов.",
            "next_action": "Проверьте очередь ручной проверки.",
            "sources": ["transaction:TRANSACTION-3302"],
        }
        result = LLMResult("{}", "gpt-4.1-mini", 100, 50, 0.1, 1)
        return payload, result


class UnsafeFakeClient:
    def chat_json(self, messages, **kwargs):
        payload = {
            "diagnosis": "Операция уже помечена duplicate.",
            "reply": "Удалите или скройте повторную строку.",
            "next_action": "Удалить TRANSACTION-3302.",
            "sources": [],
        }
        result = LLMResult("{}", "gpt-4.1-mini", 100, 50, 0.1, 1)
        return payload, result


class BalancePromiseFakeClient:
    def chat_json(self, messages, **kwargs):
        payload = {
            "diagnosis": "Возврат pending.",
            "reply": "После posted возврат автоматически появится в балансе.",
            "next_action": "Гарантировать автоматическое обновление.",
            "sources": [],
        }
        result = LLMResult("{}", "gpt-4.1-mini", 100, 50, 0.1, 1)
        return payload, result


def test_support_joins_ticket_user_and_transactions():
    result = support.answer_ticket("ADVENT-101", client=FakeClient(), bridge=FakeBridge())
    assert result["card"]["user"]["id"] == "U-1001"
    assert result["answer"]["diagnosis"].startswith("Повторный")
    assert any("TRANSACTION-3302" in hit.document.text for hit in result["hits"])
    assert any(hit.document.source == "docs/faq.md" for hit in result["hits"])
    assert all("TRANSACTION-3308" not in hit.document.text for hit in result["hits"])


def test_support_guardrail_blocks_deletion_advice():
    result = support.answer_ticket("ADVENT-101", client=UnsafeFakeClient(), bridge=FakeBridge())
    answer = result["answer"]
    assert "исключена" in answer["reply"]
    assert "без изменений" in answer["next_action"]


def test_support_guardrail_blocks_balance_promise():
    result = support.answer_ticket("ADVENT-102", client=BalancePromiseFakeClient(), bridge=FakeBridge())
    answer = result["answer"]
    assert "автомат" not in answer["reply"].lower()
    assert "баланс" not in answer["reply"].lower()
    assert "ручную проверку" in answer["next_action"]


def test_second_tenant_is_not_returned_for_primary_ticket():
    card = support_tools.get_ticket("ADVENT-102")
    assert card["user"]["id"] == card["ticket"]["user_id"] == "U-1001"
