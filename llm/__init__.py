"""LLM-client met auto-model-picker.

Voorkomt dat een hardgecodeerde model-string crasht zodra OpenAI een model
deprecated. Auto-mode: code kiest zelf een werkend model uit een prefererelijst.
"""
from .openai_client import call_openai, pick_chat_model, OpenAIError

__all__ = ["call_openai", "pick_chat_model", "OpenAIError"]
