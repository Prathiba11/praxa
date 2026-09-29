"""Turning generated text into files a recruiter can open."""

from career_copilot.documents.drafts import Draft, DraftStore, drafts
from career_copilot.documents.word import markdown_to_docx

__all__ = ["Draft", "DraftStore", "drafts", "markdown_to_docx"]
