from __future__ import annotations

import json
import unittest

from backend.llm.openai_compatible import OpenAICompatibleChatClient, OpenAICompatibleConfig, LLMClientError


class FakeHTTPResponse:
    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body, ensure_ascii=False).encode("utf-8")

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self._body


class FakeOpener:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.requests = []

    def __call__(self, req, timeout: float):
        self.requests.append((req, timeout))
        return FakeHTTPResponse(self.response)


class TestOpenAICompatibleClient(unittest.TestCase):
    def test_chat_extracts_content(self) -> None:
        opener = FakeOpener(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"tool":"filesystem","action":"write_file","resource":"/tmp/a.txt","params":{},"risk":"medium"}'
                        }
                    }
                ]
            }
        )
        client = OpenAICompatibleChatClient(
            OpenAICompatibleConfig(base_url="http://example.com/v1", api_key="key", model="demo", timeout=12.0),
            opener=opener,
        )

        content = client.chat([{"role": "user", "content": "hi"}])

        self.assertIn("write_file", content)
        self.assertEqual(len(opener.requests), 1)
        req, timeout = opener.requests[0]
        self.assertEqual(req.full_url, "http://example.com/v1/chat/completions")
        self.assertEqual(timeout, 12.0)
        body = json.loads(req.data.decode("utf-8"))
        self.assertEqual(body["model"], "demo")
        self.assertEqual(body["messages"][0]["content"], "hi")
        self.assertEqual(body["response_format"], {"type": "json_object"})

    def test_missing_choices_raises(self) -> None:
        opener = FakeOpener({"wrong": True})
        client = OpenAICompatibleChatClient(
            OpenAICompatibleConfig(base_url="http://example.com/v1", api_key="key", model="demo"),
            opener=opener,
        )

        with self.assertRaises(LLMClientError):
            client.chat([{"role": "user", "content": "hi"}])

    def test_prefers_tool_calls_and_maps_to_react_action(self) -> None:
        opener = FakeOpener(
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "filesystem.read_file",
                                        "arguments": '{"resource":"/tmp/a.txt","params":{},"risk":"medium"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        )
        client = OpenAICompatibleChatClient(
            OpenAICompatibleConfig(base_url="http://example.com/v1", api_key="key", model="demo"),
            opener=opener,
        )

        text = client.chat([{"role": "user", "content": "read"}])
        payload = json.loads(text)

        self.assertEqual(payload["type"], "action")
        self.assertEqual(payload["function_call"]["name"], "filesystem.read_file")
        self.assertEqual(payload["function_call"]["arguments"]["resource"], "/tmp/a.txt")
        self.assertEqual(payload["function_call"]["id"], "call_1")

    def test_tool_calls_invalid_arguments_raises(self) -> None:
        opener = FakeOpener(
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "filesystem.read_file",
                                        "arguments": "not-json",
                                    }
                                }
                            ],
                        }
                    }
                ]
            }
        )
        client = OpenAICompatibleChatClient(
            OpenAICompatibleConfig(base_url="http://example.com/v1", api_key="key", model="demo"),
            opener=opener,
        )

        with self.assertRaises(LLMClientError):
            client.chat([{"role": "user", "content": "read"}])

    def test_multiple_tool_calls_maps_to_action_batch(self) -> None:
        opener = FakeOpener(
            {
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_a",
                                    "function": {
                                        "name": "filesystem.read_file",
                                        "arguments": '{"resource":"/tmp/a.txt","params":{},"risk":"medium"}',
                                    }
                                },
                                {
                                    "id": "call_b",
                                    "function": {
                                        "name": "filesystem.list_dir",
                                        "arguments": '{"resource":"/tmp","params":{},"risk":"medium"}',
                                    }
                                },
                            ],
                        }
                    }
                ]
            }
        )
        client = OpenAICompatibleChatClient(
            OpenAICompatibleConfig(base_url="http://example.com/v1", api_key="key", model="demo"),
            opener=opener,
        )

        text = client.chat([{"role": "user", "content": "multi"}])
        payload = json.loads(text)

        self.assertEqual(payload["type"], "action_batch")
        self.assertEqual(len(payload["function_calls"]), 2)
        self.assertEqual(payload["function_calls"][1]["name"], "filesystem.list_dir")
        self.assertEqual(payload["function_calls"][0]["id"], "call_a")
        self.assertEqual(payload["function_calls"][1]["id"], "call_b")


if __name__ == "__main__":
    unittest.main()
