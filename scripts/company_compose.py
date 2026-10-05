"""Keep prepared company settings independent of the caller's shell variables."""
import os
import re


def compose_environment(source: str, values: dict[str, str] | None = None) -> dict[str, str]:
    variables = set(re.findall(r'\$\{([A-Za-z_][A-Za-z0-9_]*)', source))
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() not in variables and not key.upper().startswith('COMPOSE_')}
    environment.update(values or {})
    return environment
