"""Interpretation engine: LLM reviewer for MD&A and note summaries with evidence."""

from src.pipeline.interpret.interpretations import generate_interpretations

__all__ = ["generate_interpretations"]
