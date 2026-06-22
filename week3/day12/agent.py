from api_client import ApiClient
from config import MAX_COMPLETION_TOKENS, SYSTEM_MESSAGE
from memory import MemoryLayers
from profile import ProfileStore


class AssistantAgent:
    def __init__(self):
        self.system_message = SYSTEM_MESSAGE
        self.memory = MemoryLayers()
        self.profile = ProfileStore()
        self.client = ApiClient()

    def build_messages(self):
        return self.memory.build_messages(
            self.system_message,
            extra_system=[self.profile.as_prompt()],
        )

    def ask(self, user_text):
        self.memory.add_dialog("user", user_text)
        messages = self.build_messages()
        answer, usage = self.client.chat(messages, max_tokens=MAX_COMPLETION_TOKENS)
        self.memory.add_dialog("assistant", answer)
        return answer, usage, messages

    def compare_profiles(self, question):
        result = []
        for name, profile in self.profile.list_profiles().items():
            messages = [
                {"role": "system", "content": self.system_message},
                {"role": "system", "content": self.profile.as_prompt(profile=profile, name=name)},
                {"role": "user", "content": question},
            ]
            answer, usage = self.client.chat(messages)
            result.append((name, profile, answer, usage))
        return result
