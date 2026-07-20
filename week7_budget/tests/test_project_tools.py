import pytest

from budget_pipeline import project_tools


def test_project_reader_blocks_path_escape():
    with pytest.raises(project_tools.ToolError):
        project_tools.read_file("../.zshrc")


def test_generated_writer_requires_confirmation():
    with pytest.raises(project_tools.ToolError):
        project_tools.write_generated_file("test.md", "content", confirm=False)

