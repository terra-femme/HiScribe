# vertex_ai.py — GCP Vertex AI LLM Adapter (Stub)

## What This File Is For
Placeholder for Google Cloud Vertex AI as the LLM provider (Gemini models). The GCP alternative to OpenAI for the SOAP mapping step.

## What a Real Implementation Would Need
- `google-cloud-aiplatform` Python package
- `GOOGLE_APPLICATION_CREDENTIALS` and `GCP_PROJECT_ID` env vars
- Use `vertexai.generative_models.GenerativeModel` with `gemini-1.5-flash` or `gemini-pro`
- Same MAP_PROMPT and `_validate_mappings` logic as `openai_api.py`
- Vertex AI is HIPAA-eligible under Google Cloud's BAA

**ELI5:** Same job as the OpenAI adapter, but using Google's AI instead of OpenAI's.

## Key Concepts To Look Up
- Vertex AI Generative AI SDK for Python
- Gemini model family — `flash` (fast/cheap) vs `pro` (capable)
- GCP HIPAA compliance — Google Cloud's BAA coverage
