from types import SimpleNamespace

import pytest

from app.ai import AIProviderError
from app.config import Settings
from app.cv_ai import (
    CV_PROMPT_VERSION,
    FallbackCvExtractionProvider,
    MockCvExtractionProvider,
    OpenAICvExtractionProvider,
    build_cv_provider,
    empty_draft,
)


class FakeResponses:
    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


class FakeProvider:
    def __init__(self, error: bool = False):
        self.error = error
        self.calls = 0

    def extract(self, *, pages, sections):
        self.calls += 1
        if self.error:
            raise AIProviderError("safe")
        return MockCvExtractionProvider("fake").extract(pages=pages, sections=sections)


def openai_provider(responses: FakeResponses) -> OpenAICvExtractionProvider:
    provider = object.__new__(OpenAICvExtractionProvider)
    provider.settings = Settings(
        _env_file=None,
        ai_generation_mode="openai",
        openai_api_key="test-key",
        ai_max_output_tokens=800,
    )
    provider.client = SimpleNamespace(responses=responses)
    return provider


def test_mock_parser_handles_empty_and_contact_urls_without_duplicates():
    empty, metadata = MockCvExtractionProvider().extract(pages=[], sections={})
    assert empty.personal.full_name.value is None
    assert metadata.prompt_version == CV_PROMPT_VERSION

    draft, _ = MockCvExtractionProvider().extract(
        pages=[
            {
                "page": 1,
                "text": (
                    "Jane Candidate\nSenior Engineer\njane@example.com\n+351 912 345 678\n"
                    "https://linkedin.com/in/jane\nhttps://github.com/jane\nPython and Python"
                ),
            }
        ],
        sections={},
    )
    assert draft.personal.linkedin_url.value == "https://linkedin.com/in/jane"
    assert draft.personal.github_url.value == "https://github.com/jane"
    assert draft.personal.phone.value == "+351 912 345 678"
    assert [item.value for item in draft.technical_skills] == ["Python"]


def test_openai_cv_provider_uses_strict_private_response_and_metadata():
    parsed = empty_draft()
    responses = FakeResponses(
        SimpleNamespace(
            output_parsed=parsed,
            usage=SimpleNamespace(input_tokens=123, output_tokens=45),
            id="response-1",
        )
    )
    provider = openai_provider(responses)

    result, metadata = provider.extract(
        pages=[{"page": 1, "text": "<ignore> & data"}], sections={"skills": [1]}
    )

    assert result == parsed
    assert metadata.provider_response_id == "response-1"
    assert (metadata.input_tokens, metadata.output_tokens) == (123, 45)
    assert responses.kwargs["text_format"] is type(parsed)
    assert responses.kwargs["store"] is False
    prompt = responses.kwargs["input"][1]["content"]
    assert "\\u003cignore\\u003e" in prompt and "\\u0026" in prompt


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (SimpleNamespace(output_parsed=None, usage=None), "returned no structured result"),
        (RuntimeError("provider secret"), "provider request failed"),
    ],
)
def test_openai_cv_provider_redacts_failures(response, message):
    responses = (
        FakeResponses(error=response)
        if isinstance(response, Exception)
        else FakeResponses(response=response)
    )
    with pytest.raises(AIProviderError, match=message):
        openai_provider(responses).extract(pages=[{"page": 1, "text": "data"}], sections={})


def test_cv_provider_factory_and_fallback():
    assert isinstance(build_cv_provider(Settings(_env_file=None)), MockCvExtractionProvider)
    primary, fallback = FakeProvider(error=True), FakeProvider()
    draft, metadata = FallbackCvExtractionProvider(primary, fallback).extract(
        pages=[{"page": 1, "text": "Jane Candidate"}], sections={}
    )
    assert draft.personal.full_name.value == "Jane Candidate"
    assert metadata.model == "fake"
    assert primary.calls == fallback.calls == 1

    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        build_cv_provider(
            Settings(_env_file=None, ai_generation_mode="mock").model_copy(
                update={"ai_generation_mode": "openai", "openai_api_key": None}
            )
        )
