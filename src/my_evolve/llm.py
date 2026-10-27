"""The LLM classes: send a prompt to a language model and return its reply (D66).

For now this module holds only is_reasoning_model, which the problem file needs
to check a model's settings; the client and the ensemble come in a later step.
"""

# The name prefixes of OpenAI's reasoning models, as openevolve recognises them (D32).
REASONING_MODEL_PREFIXES = ("o1", "o3", "o4", "gpt-5", "gpt-oss")


def is_reasoning_model(name: str) -> bool:
    """Guess from its name whether a model is one of OpenAI's reasoning models.

    These models refuse max_tokens and temperature, and need max_completion_tokens
    instead. Any provider prefix is ignored: "openai/o3" is a reasoning model.
    """
    model_name = name.rsplit("/", 1)[-1].lower()
    return model_name.startswith(REASONING_MODEL_PREFIXES)
