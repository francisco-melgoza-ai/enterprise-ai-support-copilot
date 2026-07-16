# Enterprise AI Support Copilot

## Current milestone

Build a local FastAPI service for customer-support ticket analysis.

Do not add Gemini, Google Cloud services, databases, Docker, Terraform, or
authentication during this milestone.

## Architecture rules

- API routes handle HTTP concerns only.
- Services contain business logic.
- Schemas define request and response contracts.
- Repositories will handle persistence later.
- Core contains configuration, logging, and shared application behavior.
- External AI services must be accessed through an interface.
- Never log ticket descriptions, customer messages, or personal information.

## Engineering standards

- Use Python type hints.
- Use FastAPI and Pydantic.
- Return consistent structured errors.
- Keep functions small and testable.
- Use dependency injection where useful.
- Add unit and integration tests.
- Do not add unused abstractions or dependencies.
- Update README.md when setup or behavior changes.

## Validation

Run all of the following before completing work:

- `ruff format --check .`
- `ruff check .`
- `mypy app`
- `pytest`