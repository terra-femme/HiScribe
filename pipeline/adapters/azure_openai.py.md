# azure_openai.py — Azure OpenAI LLM Adapter (Stub)

## What This File Is For
Placeholder for the Azure OpenAI SOAP mapping adapter. Azure OpenAI hosts the same GPT-4o models as OpenAI but within Microsoft's infrastructure — HIPAA-eligible with a signed BAA, private networking options, and no data used for model training.

## Why Azure OpenAI For Production
- HIPAA-eligible (patient transcript data can pass through it with a BAA)
- Data stays within Azure's compliance boundary — not used for OpenAI model training
- Supports private endpoints (data never hits the public internet)
- Same API format as `openai_api.py` — the prompt and response structure are identical

## What a Real Implementation Would Need
- `openai` Python package (Azure OpenAI uses the same SDK)
- `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_KEY`, `AZURE_OPENAI_DEPLOYMENT` env vars
- Replace `OpenAI(api_key=...)` with `AzureOpenAI(azure_endpoint=..., api_key=..., api_version=...)`
- The MAP_PROMPT and `_validate_mappings` logic are identical — copy them from `openai_api.py`

**ELI5:** Same brain (GPT-4o), different building (Azure's HIPAA-compliant data center). You use it when the data is sensitive and you need the legal paperwork to prove it's handled safely.

## Key Concepts To Look Up
- Azure OpenAI vs OpenAI API — key differences
- HIPAA compliance for cloud AI services
- Azure private endpoints for AI services
