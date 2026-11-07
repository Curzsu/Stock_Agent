"""Application chat-model boundary for OpenAI-compatible providers."""

from copy import deepcopy
from urllib.parse import urlparse

from langchain_openai import ChatOpenAI as _ChatOpenAI
from langchain_core.messages import AIMessage


class ChatOpenAI(_ChatOpenAI):
    """Preserve Google tool-call signatures across non-streaming ReAct turns.

    LangChain normalizes tool calls and drops provider extension fields. Keep the
    opaque originals in message metadata, then restore them on the matching call
    in the next request. Never invent a signature or disable Google's validation.
    """

    def _google_compat(self):
        return urlparse(str(self.openai_api_base or "")).hostname == "generativelanguage.googleapis.com"

    def _create_chat_result(self, response, generation_info=None):
        result = super()._create_chat_result(response, generation_info)
        if self._google_compat():
            raw = response if isinstance(response, dict) else response.model_dump()
            for generation, choice in zip(result.generations, raw.get("choices", [])):
                calls = choice.get("message", {}).get("tool_calls") or []
                if calls:
                    generation.message.additional_kwargs["gemini_tool_calls"] = deepcopy(calls)
        return result

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        if not self._google_compat():
            return payload
        messages = self._convert_input(input_).to_messages()
        for message, encoded in zip(messages, payload.get("messages", [])):
            if not isinstance(message, AIMessage):
                continue
            originals = {call.get("id"): call for call in message.additional_kwargs.get("gemini_tool_calls", [])}
            for call in encoded.get("tool_calls", []):
                original = originals.get(call.get("id"), {})
                extra = original.get("extra_content") or {}
                if (original.get("function", {}).get("name") == call.get("function", {}).get("name")
                        and "thought_signature" in (extra.get("google") or {})):
                    call["extra_content"] = deepcopy(extra)
        return payload
