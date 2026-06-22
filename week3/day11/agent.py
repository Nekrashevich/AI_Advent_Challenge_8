from api_client import ApiClient
from config import MAX_COMPLETION_TOKENS, SYSTEM_MESSAGE
from memory import MemoryLayers


class AssistantAgent:
    def __init__(self):
        self.system_message = SYSTEM_MESSAGE
        self.memory = MemoryLayers()
        self.client = ApiClient()

    def ask(self, user_text):
        self.memory.add_dialog("user", user_text)
        messages = self.memory.build_messages(self.system_message)
        answer, usage = self.client.chat(messages, max_tokens=MAX_COMPLETION_TOKENS)
        self.memory.add_dialog("assistant", answer)
        return answer, usage, messages

    def compare_with_memory(self, question):
        base = [
            {"role": "system", "content": self.system_message},
            {"role": "user", "content": question},
        ]
        memory_messages = self.memory.build_messages(self.system_message, include_dialog=False)
        memory_messages.append({
            "role": "system",
            "content": "Отвечай на русском языке.",
        })
        memory_messages.append({"role": "user", "content": question})
        answer_off, usage_off = self.client.chat(base)
        answer_on, usage_on = self.client.chat(memory_messages)
        return answer_off, usage_off, answer_on, usage_on
