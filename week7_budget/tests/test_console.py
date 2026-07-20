from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from budget_pipeline.console import CommandCompleter


def test_command_completion_preserves_week6_style():
    completer = CommandCompleter()
    completions = list(completer.get_completions(Document("/demo day3"), CompleteEvent()))
    assert completions
    assert completions[0].text.startswith("/demo day3")

