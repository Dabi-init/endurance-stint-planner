"""Focused regressions for the optional local-model safety boundary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pitwall.agent import PitwallAgent
from pitwall.config import Settings
from pitwall.providers import ModelMessage, OllamaProvider, ProviderError, ToolCall
from pitwall.workspace import PitwallWorkspace


class FakeProvider:
    name = "fake"

    def __init__(self, responses: list[ModelMessage]) -> None:
        self.responses = list(responses)
        self.messages: list[list[dict]] = []

    def chat(self, messages: list[dict], tools: list[dict]) -> ModelMessage:
        self.messages.append([dict(message) for message in messages])
        assert tools
        return self.responses.pop(0)


class ByteResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self.payload if size < 0 else self.payload[:size]


@pytest.fixture
def workspace(tmp_path: Path) -> PitwallWorkspace:
    result = PitwallWorkspace.from_path(tmp_path / ".pitwall")
    result.initialise()
    return result


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (
            {"message": {"content": "", "tool_calls": 3}},
            "invalid tool_calls",
        ),
        (
            {"message": {"content": "", "tool_calls": ["bad"]}},
            "invalid tool call",
        ),
        (
            {
                "message": {
                    "content": "",
                    "tool_calls": [{"function": "bad"}],
                }
            },
            "invalid tool function",
        ),
        (
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "plan_race",
                                "arguments": [],
                            }
                        }
                    ],
                }
            },
            "invalid tool arguments",
        ),
        ({"message": {"content": {}}}, "invalid assistant content"),
    ],
)
def test_provider_rejects_malformed_nested_chat_shapes(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict,
    message: str,
) -> None:
    monkeypatch.setattr(
        "pitwall.providers.urlopen",
        lambda request, timeout: ByteResponse(json.dumps(payload).encode()),
    )
    provider = OllamaProvider(Settings(provider="ollama", model="local"))

    with pytest.raises(ProviderError, match=message):
        provider.chat([{"role": "user", "content": "plan"}], [])


def test_provider_rejects_invalid_utf8_and_nonfinite_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            ByteResponse(b"\xff"),
            ByteResponse(b'{"message":{"content":NaN}}'),
        ]
    )
    monkeypatch.setattr(
        "pitwall.providers.urlopen",
        lambda request, timeout: next(responses),
    )
    provider = OllamaProvider(Settings(provider="ollama", model="local"))

    with pytest.raises(ProviderError, match="invalid UTF-8"):
        provider.chat([], [])
    with pytest.raises(ProviderError, match="invalid JSON"):
        provider.chat([], [])


def test_provider_rejects_malformed_model_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pitwall.providers.urlopen",
        lambda request, timeout: ByteResponse(b'{"models":3}'),
    )
    provider = OllamaProvider(Settings(provider="ollama", model="local"))

    with pytest.raises(ProviderError, match="invalid model list"):
        provider.list_models()


def test_provider_caps_local_response_size(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("pitwall.providers.MAX_PROVIDER_RESPONSE_BYTES", 8)
    monkeypatch.setattr(
        "pitwall.providers.urlopen",
        lambda request, timeout: ByteResponse(b"123456789"),
    )
    provider = OllamaProvider(Settings(provider="ollama", model="local"))

    with pytest.raises(ProviderError, match="8 MiB safety limit"):
        provider.chat([], [])


def test_model_race_prose_is_replaced_without_a_successful_relevant_tool(
    workspace: PitwallWorkspace,
) -> None:
    provider = FakeProvider(
        [
            ModelMessage(tool_calls=(ToolCall("run_shell", {"command": "whoami"}),)),
            ModelMessage(content="Run 999 laps with 99 stops. Trust me."),
        ]
    )

    reply = PitwallAgent(workspace, provider=provider).ask(
        "Can we remove a stop, and what do we give up?"
    )

    assert reply.mode == "ollama-guarded"
    assert reply.used_tools == ("compare_race_strategies",)
    assert "999" not in reply.answer
    assert "Trade-offs from the deterministic comparison" in reply.answer
    assert "demo (no current race)" in reply.answer
    assert any("run_shell" in warning for warning in reply.warnings)


def test_successful_tool_result_replaces_unchecked_model_race_facts(
    workspace: PitwallWorkspace,
) -> None:
    provider = FakeProvider(
        [
            ModelMessage(
                tool_calls=(ToolCall("compare_race_strategies", {}),),
                raw_message={
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "compare_race_strategies",
                                "arguments": {},
                            }
                        }
                    ],
                },
            ),
            ModelMessage(content="Run 999 laps with 99 stops."),
        ]
    )

    reply = PitwallAgent(workspace, provider=provider).ask(
        "Which race strategy should we run?"
    )

    assert reply.mode == "ollama"
    assert reply.used_tools == ("compare_race_strategies",)
    assert "999" not in reply.answer
    assert "Input source: **Manual assumptions**" in reply.answer
    assert "P10" in reply.answer and "P90" in reply.answer
    assert "Trade-offs from the deterministic comparison" in reply.answer
    assert len(provider.messages) == 1


def test_successful_but_irrelevant_tool_does_not_ground_strategy_prose(
    workspace: PitwallWorkspace,
) -> None:
    provider = FakeProvider(
        [
            ModelMessage(tool_calls=(ToolCall("check_driver_rules", {}),)),
            ModelMessage(content="Run 999 laps with 99 stops."),
        ]
    )

    reply = PitwallAgent(workspace, provider=provider).ask("Can we remove a stop?")

    assert reply.mode == "ollama-guarded"
    assert reply.used_tools == ("compare_race_strategies",)
    assert "999" not in reply.answer
    assert [entry["tool"] for entry in reply.trace] == [
        "check_driver_rules",
        "compare_race_strategies",
    ]


def test_model_tool_cannot_override_an_explicit_out_of_scope_answer(
    workspace: PitwallWorkspace,
) -> None:
    provider = FakeProvider(
        [
            ModelMessage(tool_calls=(ToolCall("compare_race_strategies", {}),)),
            ModelMessage(content="It will be sunny; run 999 laps."),
        ]
    )

    reply = PitwallAgent(workspace, provider=provider).ask("What is the weather?")

    assert reply.mode == "ollama-guarded"
    assert reply.used_tools == ()
    assert "no live timing, weather" in reply.answer.lower()
    assert "999" not in reply.answer
    assert reply.trace[0]["result"]["ok"] is False
    assert "not relevant" in reply.trace[0]["result"]["error"]


def test_model_cannot_export_without_explicit_user_intent(
    workspace: PitwallWorkspace,
) -> None:
    provider = FakeProvider(
        [
            ModelMessage(
                tool_calls=(ToolCall("export_pit_sheet", {"name": "surprise"}),)
            ),
            ModelMessage(content="Created it."),
        ]
    )

    reply = PitwallAgent(workspace, provider=provider).ask(
        "What information is in a pit sheet?"
    )

    assert not (workspace.reports_dir / "surprise.md").exists()
    assert reply.used_tools == ()
    assert any("did not explicitly ask" in warning for warning in reply.warnings)


@pytest.mark.parametrize(
    "prompt",
    [
        "Do not export a pit sheet",
        "Never export this report",
        "Export only after I confirm",
        "Explain export without creating anything",
        "Don't make a pit sheet",
    ],
)
def test_model_cannot_turn_negative_or_conditional_export_into_a_write(
    workspace: PitwallWorkspace,
    prompt: str,
) -> None:
    provider = FakeProvider(
        [
            ModelMessage(
                tool_calls=(ToolCall("export_pit_sheet", {"name": "surprise"}),)
            ),
            ModelMessage(content="Created it."),
        ]
    )

    reply = PitwallAgent(workspace, provider=provider).ask(prompt)

    assert not (workspace.reports_dir / "surprise.md").exists()
    assert "Created it" not in reply.answer


def test_explicit_affirmative_export_can_create_one_new_sheet(
    workspace: PitwallWorkspace,
) -> None:
    provider = FakeProvider(
        [ModelMessage(tool_calls=(ToolCall("export_pit_sheet", {"name": "approved"}),))]
    )

    reply = PitwallAgent(workspace, provider=provider).ask(
        "Please export a pit sheet named approved"
    )

    assert (workspace.reports_dir / "approved.md").exists()
    assert reply.used_tools == ("export_pit_sheet",)


def test_safety_car_answer_keeps_authoritative_disclaimer(
    workspace: PitwallWorkspace,
) -> None:
    provider = FakeProvider(
        [
            ModelMessage(
                tool_calls=(
                    ToolCall(
                        "simulate_safety_car",
                        {"deploy_min": 120, "duration_min": 20},
                    ),
                )
            ),
            ModelMessage(content="This is live race control; gain 999 laps."),
        ]
    )

    reply = PitwallAgent(workspace, provider=provider).ask(
        "Safety Car at 120 for 20 minutes"
    )

    assert "999" not in reply.answer
    assert "PRE-RACE WHAT-IF ONLY" in reply.answer
    assert "PRE-RACE PLAN ONLY" in reply.answer
    assert "Input source: **Manual assumptions**" in reply.answer


def test_model_cannot_change_labeled_safety_car_times_or_skip_unit_conversion(
    workspace: PitwallWorkspace,
) -> None:
    provider = FakeProvider(
        [
            ModelMessage(
                tool_calls=(
                    ToolCall(
                        "simulate_safety_car",
                        {"deploy_min": 2, "duration_min": 999},
                    ),
                )
            )
        ]
    )

    reply = PitwallAgent(workspace, provider=provider).ask(
        "Safety Car deployment at 2 hours, duration 20 minutes"
    )

    assert reply.used_tools == ("simulate_safety_car",)
    assert reply.trace[0]["arguments"] == {
        "deploy_min": 120.0,
        "duration_min": 20.0,
    }


@pytest.mark.parametrize(
    ("prompt", "deploy_min", "duration_min"),
    [
        ("Safety Car at 120 for 20 minutes", 120.0, 20.0),
        ("Safety Car for 20 minutes at minute 120", 120.0, 20.0),
        (
            "Safety Car deployment at 2 hours, duration of 20 minutes",
            120.0,
            20.0,
        ),
        ("SC after 1.5 hours lasting 0.25 hours", 90.0, 15.0),
    ],
)
def test_deterministic_safety_car_parser_uses_labels_and_converts_units(
    workspace: PitwallWorkspace,
    prompt: str,
    deploy_min: float,
    duration_min: float,
) -> None:
    reply = PitwallAgent(workspace).ask(prompt)

    assert reply.used_tools == ("simulate_safety_car",)
    assert reply.trace[0]["arguments"] == {
        "deploy_min": deploy_min,
        "duration_min": duration_min,
    }


@pytest.mark.parametrize(
    "prompt",
    [
        "Safety Car 120 20",
        "Safety Car at 120 and 20 minutes",
        "Safety Car at 120 minutes for 20 minutes after lap 4",
        "Safety Car at 120 minutes for 20 minutes, duration 30 minutes",
    ],
)
def test_deterministic_safety_car_parser_rejects_ambiguous_numbers(
    workspace: PitwallWorkspace,
    prompt: str,
) -> None:
    reply = PitwallAgent(workspace).ask(prompt)

    assert reply.used_tools == ()
    assert reply.trace == ()
    assert "label one deployment time" in reply.answer


def test_model_cannot_supply_arguments_for_an_ambiguous_safety_car_prompt(
    workspace: PitwallWorkspace,
) -> None:
    provider = FakeProvider(
        [
            ModelMessage(
                tool_calls=(
                    ToolCall(
                        "simulate_safety_car",
                        {"deploy_min": 120, "duration_min": 20},
                    ),
                )
            ),
            ModelMessage(content="The Safety Car will create 999 laps."),
        ]
    )

    reply = PitwallAgent(workspace, provider=provider).ask("Safety Car 120 20")

    assert reply.used_tools == ()
    assert "label one deployment time" in reply.answer
    assert "999" not in reply.answer
    assert reply.trace[0]["result"]["ok"] is False
    assert "not relevant" in reply.trace[0]["result"]["error"]


def test_tool_calls_are_capped_per_response_and_in_total(
    workspace: PitwallWorkspace,
) -> None:
    many_calls = ModelMessage(
        tool_calls=tuple(ToolCall("run_shell", {}) for _ in range(5))
    )
    provider = FakeProvider([many_calls, many_calls])

    reply = PitwallAgent(
        workspace,
        provider=provider,
        max_tool_calls_per_response=2,
        max_total_tool_calls=3,
    ).ask("Compare race strategies")

    assert len(provider.messages) == 2
    assert len(reply.trace) == 4
    assert reply.used_tools == ("compare_race_strategies",)
    assert any("extra calls were not executed" in item for item in reply.warnings)
    assert any("total tool-call safety limit" in item for item in reply.warnings)


def test_current_session_context_is_bounded_and_fact_free(
    workspace: PitwallWorkspace,
) -> None:
    provider = FakeProvider(
        [ModelMessage(content=f"Answer {index}") for index in range(5)]
    )
    agent = PitwallAgent(workspace, provider=provider)

    for index in range(5):
        agent.ask(f"Question {index}", session_id="same-session")

    final_messages = provider.messages[-1]
    assert len(final_messages) <= 8
    assert not any(item.get("content") == "Question 0" for item in final_messages)
    markers = [
        item["content"] for item in final_messages if item.get("role") == "assistant"
    ]
    assert markers
    assert all("authoritative deterministic output" in item for item in markers)
    assert all("projected laps" not in item for item in markers)


def test_invalid_workspace_config_falls_back_without_crashing(
    workspace: PitwallWorkspace,
) -> None:
    workspace.config_path.write_text("provider = [broken", encoding="utf-8")

    reply = PitwallAgent(workspace).ask("Compare race strategies")

    assert reply.mode == "deterministic-fallback"
    assert reply.used_tools == ("compare_race_strategies",)
    assert any("Invalid Pitwall configuration" in item for item in reply.warnings)
    assert not workspace.memory_path.exists()


def test_malformed_ipv6_ollama_host_falls_back_without_crashing(
    workspace: PitwallWorkspace,
) -> None:
    workspace.config_path.write_text(
        'provider = "ollama"\nmodel = "local"\nollama_host = "http://[::1"\n',
        encoding="utf-8",
    )

    reply = PitwallAgent(workspace).ask("Compare race strategies")

    assert reply.mode == "deterministic-fallback"
    assert reply.used_tools == ("compare_race_strategies",)


def test_raw_model_prose_cannot_answer_an_unfamiliar_race_paraphrase(
    workspace: PitwallWorkspace,
) -> None:
    provider = FakeProvider([ModelMessage(content="Box now for 999 litres.")])

    reply = PitwallAgent(workspace, provider=provider).ask("When should we box?")

    assert "999" not in reply.answer
    assert reply.used_tools == ("compare_race_strategies",)


def test_referential_followup_reuses_the_last_authoritative_tool(
    workspace: PitwallWorkspace,
) -> None:
    provider = FakeProvider(
        [
            ModelMessage(tool_calls=(ToolCall("compare_race_strategies", {}),)),
            ModelMessage(content="Because I guessed 999 laps."),
        ]
    )
    agent = PitwallAgent(workspace, provider=provider)
    first = agent.ask("Which strategy should we run?", session_id="same")
    followup = agent.ask("Why?", session_id="same")

    assert first.used_tools == ("compare_race_strategies",)
    assert followup.used_tools == ("compare_race_strategies",)
    assert "999" not in followup.answer


def test_referential_followup_keeps_the_prior_tool_relevant_to_the_model(
    workspace: PitwallWorkspace,
) -> None:
    provider = FakeProvider(
        [
            ModelMessage(tool_calls=(ToolCall("compare_race_strategies", {}),)),
            ModelMessage(tool_calls=(ToolCall("compare_race_strategies", {}),)),
        ]
    )
    agent = PitwallAgent(workspace, provider=provider)

    first = agent.ask("Which strategy should we run?", session_id="same")
    followup = agent.ask("Why?", session_id="same")

    assert first.used_tools == ("compare_race_strategies",)
    assert followup.mode == "ollama"
    assert followup.used_tools == ("compare_race_strategies",)


def test_oversized_prompt_is_not_sent_to_model_or_history(
    workspace: PitwallWorkspace,
) -> None:
    provider = FakeProvider([ModelMessage(content="should not run")])

    reply = PitwallAgent(workspace, provider=provider).ask("x" * 8_001)

    assert provider.messages == []
    assert "8,000-character" in reply.answer
    assert not workspace.memory_path.exists()
