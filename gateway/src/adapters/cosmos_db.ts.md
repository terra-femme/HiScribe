# cosmos_db.ts — Azure Cosmos DB Storage Adapter (Stub)

## What This File Is For
A placeholder for the Azure Cosmos DB storage adapter. All four functions throw `NotImplementedError` immediately. This file exists to define the contract — the function signatures that a real Cosmos DB implementation would need to fulfill.

## How It Fits In The Project
`storage.ts` has a commented-out line pointing to this file. When you're ready to move to Azure, uncomment that line, implement these four functions, and the rest of the codebase stays unchanged.

---

## What a Real Implementation Would Need
- `@azure/cosmos` npm package
- `AZURE_COSMOS_ENDPOINT` and `AZURE_COSMOS_KEY` environment variables
- A Cosmos DB account, database, and container pre-created in Azure portal
- The same four function signatures: `saveSession`, `getSession`, `saveSegment`, `getSegments`

## Why Stubs Exist
Stubs enforce the interface at the file level. If `cosmos_db.ts` didn't exist, swapping to it in `storage.ts` would cause an immediate import error rather than a clean "not implemented" message at runtime.

**ELI5:** It's like having a locked door with a sign that says "Azure storage — under construction." You know where the door is, you know what's behind it, and you know exactly what you need to build.

## Key Concepts To Look Up
- Azure Cosmos DB — document database, how it differs from SQLite
- Azure SDK for JavaScript (`@azure/cosmos`)
- NoSQL vs relational databases — when to use which
