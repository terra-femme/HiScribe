# HiScribe ⇄ Mirth Connect — HL7 v2 / FHIR interface

Bidirectional integration between HiScribe and a **simulated** EHR and
practice-management system, built on [Mirth Connect](https://github.com/nextgenhealthcare/connect) 4.4.2.

```
                    ADT^A01/A04/A08
  Registration ───────MLLP:6661──────▶ ADT_Inbound ──REST──▶ pipeline
   (send_adt.py)                       parse PID/PV1        /fhir/patient-context
                                                                   │
                                                            patient_context
                                                              (SQLite)

  ┌──────────────────────────────────────────────────────────────────────┐
  │  provider records → LangGraph → SOAP note → provider approves        │
  └──────────────────────────────────────────────────────────────────────┘
                                    │
          FHIR R4B Bundle           │           FHIR ChargeItem + Condition
          (Composition)             │           (provider-confirmed only)
                 │                  │                        │
          HTTP :8081/note/          │                 HTTP :8082/charge/
                 ▼                  │                        ▼
          Note_Outbound             │                 Charge_Outbound
     Composition → MDM^T02          │            ChargeItem → DFT^P03
                 │                  │                        │
            MLLP:6662               │                   MLLP:6663
                 ▼                  │                        ▼
            EHR_Mock                │                    PM_Mock
       writes chart document        │              writes charge posting
          returns ACK ──────────────┴──────────────────▶ returns ACK
                          (MSA-1 returned to caller)
```

> **This is a simulated environment.** `EHR_Mock` and `PM_Mock` are channels in
> this repository that write received messages to disk. They are not Epic,
> Cerner, or any commercial product, and every message is synthetic. Nothing
> here is experience with a vendor EHR or with real patient data.

---

## Run it

### 1. Prerequisites

| | |
|---|---|
| Docker Desktop | running — the whole stack is containerised |
| Python | 3.13 for the tooling in `mirth/tools/` |
| `requests`, `defusedxml` | `pip install requests defusedxml` (used by the deploy tool) |

`dev_context_listener.py` binds loopback by default. It needs `--host 0.0.0.0`
to accept connections from the Mirth container, since `host.docker.internal`
does not resolve to `127.0.0.1` from inside it.

The image is ~1.9 GB and is pulled on first start.

### 2. Start Mirth

```powershell
docker compose up -d mirth
```

Wait for the healthcheck (up to ~90 s on first boot):

```powershell
docker compose ps mirth
```

You want `STATUS` to read `healthy`. Verify the API directly:

```powershell
curl.exe -sk -u admin:admin -H "X-Requested-With: cli" https://localhost:8443/api/server/version
```

Expected output: `4.4.2`

### 3. Build and deploy the channels

Channels are **not** baked into the image.

```powershell
python mirth/tools/build_channels.py
python mirth/tools/deploy_channels.py
```

Expected final lines:

```
INFO  [deploy]   ADT_Inbound      STARTED
INFO  [deploy]   Charge_Outbound  STARTED
INFO  [deploy]   EHR_Mock         STARTED
INFO  [deploy]   Note_Outbound    STARTED
INFO  [deploy]   PM_Mock          STARTED
INFO  [deploy] All 5 channels STARTED
```

Anything other than `STARTED` is a real failure — see *Troubleshooting*.

### 4. Send an ADT message

```powershell
python mirth/tools/send_adt.py --mrn MRN990011 --family ALVAREZ --given MARIA
```

You should get `MSA|AA|<control id>` back. To see it land in the database, run
the development listener in another terminal first:

```powershell
python mirth/tools/dev_context_listener.py --db data/hiscribe_dev.db --host 0.0.0.0
```

(The real endpoint is `POST /fhir/patient-context` in `pipeline/server.py`.
`dev_context_listener.py` calls the same `save_patient_context()` without
pulling in torch and tensorflow.)

### 5. Send a note

With the pipeline running, approving a session emits the bundle automatically —
`pipeline/interop/client.py` selects the sink. To exercise the channel directly:

```powershell
curl.exe -X POST "http://localhost:8081/note/" `
  -H "Content-Type: application/fhir+json; charset=utf-8" `
  -H "X-HiScribe-Session: sess-demo-001" `
  --data "@bundle.json"
```

The response body is the **downstream ACK**, not Mirth's own. Received messages
land in `data/mirth/ehr_inbox/`.

### Ports

| Port | Channel | Protocol |
|---|---|---|
| 8443 | Mirth administrator / REST API | HTTPS |
| 6661 | `ADT_Inbound` | MLLP |
| 6662 | `EHR_Mock` | MLLP |
| 6663 | `PM_Mock` | MLLP |
| 8081 | `Note_Outbound` — `POST /note/` | HTTP |
| 8082 | `Charge_Outbound` — `POST /charge/` | HTTP |

---

## Layout

```
mirth/
  transformers/            the mapping logic, as readable JavaScript
    adt_inbound.js           ADT PID/PV1 → patient-context JSON
    note_outbound_mdm.js     FHIR Composition → MDM^T02
    charge_outbound_dft.js   FHIR ChargeItem → DFT^P03
  channels/                generated, committed, importable into any Mirth 4.4
  tools/
    build_channels.py        transformers + specs → channel XML
    deploy_channels.py       import, enable, deploy, verify
    send_adt.py              synthetic ADT over MLLP
    dev_context_listener.py  lightweight stand-in for the pipeline endpoint
```

The mapping logic lives in `.js` files rather than inside XML text nodes so it
can be read, diffed and reviewed. `build_channels.py` inlines it. Edit a
transformer, rebuild, redeploy.

---

## Mapping decisions worth defending

**`MDM^T02`** is the message a documentation system sends to file a new document
*with its content included* (HL7 v2.5 Chapter 9). `TXA` is the document header;
the body travels as `OBX` repetitions. An amendment to an already-filed document
would be `T08`.

**`TXA-17` follows the attestation.** HiScribe records the provider as the
accountable author through `Composition.attester.mode = 'legal'`. That is
exactly what `LA` — *legally authenticated* — means in HL7 table 0271. Without
that attester the transformer emits `AU` rather than claiming a legal
attestation that was never made.

**`DFT^P03`** posts charges to a billing system. `FT1-6 = CG` (Charge, table
0017); `FT1-7` and `FT1-25` carry the procedure; `FT1-19` and `DG1` carry the
diagnosis.

**ICD-10-CM in `FT1-19`, not SNOMED.** A `Condition` here carries *both*
codings. SNOMED CT expresses the clinical meaning and is what FHIR prefers;
ICD-10-CM is what a payer adjudicates. A DFT with SNOMED in `FT1-19` would be
well-formed and rejected by every payer. The transformer selects ICD-10
explicitly and logs when one is missing rather than falling back to whichever
coding happens to be first.

**`FT1-2` is an idempotency key.** It is derived from the session, so a charge
replayed after a network retry arrives with the same transaction id and a
billing system can reject the duplicate instead of double-billing a patient.

**E/M level is gated on a human.** Selecting a level is a billing determination
with legal and financial consequence. `suggest_charge()` produces a `planned`
ChargeItem; only `confirm_charge()` with an identified provider produces a
`billable` one, and `Charge_Outbound` independently skips anything that is not
`billable`. The gate is enforced in two systems on purpose.

**HL7 delimiters are escaped.** Clinical narrative is arbitrary speech; an
unescaped `|` or `^` silently shifts every following field. Newlines become
`\.br\`, the HL7 formatting escape, rather than terminating the segment.

---

## Code set licensing

| Code set | Status | Consequence here |
|---|---|---|
| ICD-10-CM | Public domain (CMS/CDC) | Safe to vendor |
| LOINC | Free, registration required | Safe to reference specific codes |
| SNOMED CT | UMLS licence, free for US users | Reference codes; never vendor the release |
| **CPT** | **AMA-licensed, redistribution prohibited** | **No CPT table in this repo** |

CPT codes are read from `config/cpt_codes.json`, which is **gitignored**. Copy
`config/cpt_codes.example.json` and populate it from your own AMA-licensed
source. Without it, charge capture is disabled and says so — it does not crash.

## ⚠️ Unverified terminology

The ICD-10 ↔ SNOMED crosswalk in `pipeline/interop/charge_codes.py` is marked
`verified: False` and logs a warning on every use. Those pairs were written from
general knowledge and have **not** been checked against a primary source. Before
this is used for anything beyond demonstration, verify each against CMS
(ICD-10-CM), the NLM UMLS browser (SNOMED CT), and the NLM ICD-10-CM → SNOMED
map. The same applies to the four `TODO VERIFY` URIs in `interop/codes.py`.

---

## Troubleshooting

Every item below was hit while building this, and each fails **silently**.

**Channel deploys but nothing listens; `/channels/statuses` is empty.**
The channel is disabled. A channel imported without
`exportData/metadata/enabled` defaults to disabled, and deploying a disabled
channel returns HTTP 204 having done nothing. `deploy_channels.py` sets the flag
explicitly through `PUT /server/channelMetadata`.

**Channel description becomes "This channel is invalid."**
An element name in the XML does not match a field on the connector properties
class. XStream drops the *entire connector* and Mirth still returns HTTP 200.
`deploy_channels.py` reads every channel back and fails loudly on this. Names
that bit here:

| Wrong | Right | Class |
|---|---|---|
| `maxRetryCount` | `maxRetries` | `MLLPModeProperties` |
| `updateAttachment` | `reattachAttachments` | `DestinationConnectorProperties` |
| `useHeadersVariable` | `useResponseHeadersVariable` | `HttpReceiverProperties` |
| `FileSchemeProperties` | omit for `scheme FILE` | — |

To check a field name against the running image:

```powershell
docker exec hiscribe-mirth sh -c "cd /opt/connect && unzip -p extensions/tcp/tcp-shared.jar com/mirth/connect/connectors/tcp/TcpReceiverProperties.class | strings | grep -E '^[a-z][a-zA-Z]+$' | sort -u"
```

**`NullPointerException` on deploy.** A nested properties object is null.
`sourceConnectorProperties.resourceIds`, `properties.messageStorageMode`, and
`HL7v2DataTypeProperties.serializationProperties` must all be present even when
they only carry defaults.

**POST returns 302 and the channel receives an empty message.**
Mirth's HTTP listener redirects a context path without a trailing slash. Use
`/note/`, not `/note`. A redirected POST arrives with no body.

**Non-ASCII characters are mangled (`—` becomes `â€"`).**
The request declared no charset, so Mirth fell back to the HTTP default of
ISO-8859-1. Send `Content-Type: application/fhir+json; charset=utf-8`.

**Nothing appears in `data/mirth/*_inbox`.** Check channel statistics:

```powershell
curl.exe -sk -u admin:admin -H "X-Requested-With: cli" `
  "https://localhost:8443/api/channels/a1000000-0000-4000-8000-000000000004/statistics"
```

`error` greater than zero means the transformer threw. Fetch the message with
`?includeContent=true` on `/messages` to see the raw content and the error.

---

## Reset

```powershell
python mirth/tools/deploy_channels.py --undeploy
docker compose down mirth          # add -v to discard the Derby database too
```
