/**
 * Charge_Outbound source transformer — FHIR ChargeItem -> HL7 v2.5 DFT^P03.
 *
 * The clinical-documentation to revenue-cycle handoff. Once a provider has
 * confirmed the charge, this posts it to the practice-management/billing system
 * as a Detail Financial Transaction.
 *
 * Structure, HL7 v2.5 Chapter 6:
 *   MSH, [SFT], EVN, PID, [PD1], [ROL], [PV1], [PV2], [common order],
 *   {FT1 ...}, [DG1 ...], [DRG], [GT1], [insurance], [ACC]
 *
 * FT1 fields used, verified against the v2.5 standard:
 *   FT1-1  Set ID
 *   FT1-2  Transaction ID          idempotency key, see below
 *   FT1-4  Transaction Date        DR
 *   FT1-6  Transaction Type        table 0017 -> CG (Charge)
 *   FT1-7  Transaction Code        CE, the billed procedure
 *   FT1-10 Transaction Quantity    NM
 *   FT1-11 Transaction Amount      CP, extended
 *   FT1-19 Diagnosis Code          CE, "primary diagnosis code for billing"
 *   FT1-20 Performed By Code       XCN
 *   FT1-25 Procedure Code          CE
 *
 * Why ICD-10 and not SNOMED in FT1-19 and DG1
 * -------------------------------------------
 * HiScribe emits Condition.code carrying BOTH a SNOMED CT coding (the clinical
 * meaning) and an ICD-10-CM coding (what the payer adjudicates). They are not
 * interchangeable: SNOMED expresses what the clinician meant, ICD-10-CM is what
 * goes on the claim. A DFT that put SNOMED in FT1-19 would be well-formed and
 * would still be rejected by every payer. This transformer selects the ICD-10
 * coding explicitly and logs when one is missing rather than silently falling
 * back to whichever coding happens to be first.
 *
 * Idempotency
 * -----------
 * FT1-2 is set from the ChargeItem id, which is derived from the session. A
 * charge replayed after a network retry therefore arrives with the same
 * transaction id, which is what lets a billing system reject the duplicate
 * instead of double-billing a patient. This is the single most consequential
 * field in the message.
 */

var FIELD = '|', COMP = '^';

var ICD10_SYSTEMS  = ['icd-10', 'icd10', 'sid/icd-10'];
var SNOMED_SYSTEMS = ['snomed'];

function esc(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/\\/g, '\\E\\')
        .replace(/\|/g, '\\F\\')
        .replace(/\^/g, '\\S\\')
        .replace(/~/g,  '\\R\\')
        .replace(/&/g,  '\\T\\')
        .replace(/\r\n|\r|\n/g, '\\.br\\');
}

function ts(iso) {
    var d = iso ? new Date(iso) : new Date();
    if (isNaN(d.getTime())) d = new Date();
    function p(n) { return (n < 10 ? '0' : '') + n; }
    return d.getUTCFullYear() + p(d.getUTCMonth() + 1) + p(d.getUTCDate()) +
           p(d.getUTCHours()) + p(d.getUTCMinutes()) + p(d.getUTCSeconds());
}

function collect(bundle, type) {
    var out = [], entries = (bundle && bundle.entry) || [];
    for (var i = 0; i < entries.length; i++) {
        var r = entries[i].resource;
        if (r && r.resourceType === type) out.push(r);
    }
    return out;
}

function identifierValue(resource, systemMatch) {
    if (!resource || !resource.identifier) return '';
    for (var i = 0; i < resource.identifier.length; i++) {
        var id = resource.identifier[i];
        if (!systemMatch || (id.system && id.system.indexOf(systemMatch) !== -1)) {
            return id.value || '';
        }
    }
    return resource.identifier[0].value || '';
}

/** Pick the coding whose system matches one of `wanted`. Returns null if absent. */
function codingBySystem(codeableConcept, wanted) {
    if (!codeableConcept || !codeableConcept.coding) return null;
    for (var i = 0; i < codeableConcept.coding.length; i++) {
        var c = codeableConcept.coding[i];
        var sys = (c.system || '').toLowerCase();
        for (var w = 0; w < wanted.length; w++) {
            if (sys.indexOf(wanted[w]) !== -1) return c;
        }
    }
    return null;
}

/** CE data type: identifier ^ text ^ coding system. */
function ce(coding, nameOfSystem) {
    if (!coding) return '';
    return esc(coding.code) + COMP + esc(coding.display || '') +
           COMP + (nameOfSystem || '');
}

/**
 * Read an inbound HTTP header.
 *
 * Mirth does not put headers directly on the source map — they live in a nested
 * 'headers' map, and a repeated header arrives as a List rather than a String.
 * HTTP header names are case-insensitive per RFC 7230, so an exact lookup alone
 * is not safe.
 */
function httpHeader(name) {
    try {
        var headers = sourceMap.get('headers');
        if (headers) {
            var value = headers.get(name);
            if (value === null || value === undefined) {
                var keys = headers.keySet().toArray();
                for (var k = 0; k < keys.length; k++) {
                    if (String(keys[k]).toLowerCase() === name.toLowerCase()) {
                        value = headers.get(keys[k]);
                        break;
                    }
                }
            }
            if (value !== null && value !== undefined) {
                // A repeated header is a List; take the first value.
                if (typeof value.get === 'function' && typeof value.size === 'function') {
                    return value.size() > 0 ? String(value.get(0)) : '';
                }
                return String(value);
            }
        }
    } catch (e) {
        logger.warn('[Charge_Outbound] Could not read header ' + name + ': ' + e);
    }
    var direct = sourceMap.get(name);
    return (direct === null || direct === undefined) ? '' : String(direct);
}

/**
 * XCN — extended composite ID number and name (HL7 v2.5 §2.A.89).
 * Component 9 is Assigning Authority; component 13 is Identifier Type Code.
 * Building by index avoids the caret-counting error that put 'NPI' in the
 * assigning-authority slot in an earlier version of this file.
 */
function xcn(id, family, given, identifierType) {
    var c = [];
    c[0]  = id || '';
    c[1]  = family || '';
    c[2]  = given || '';
    c[12] = identifierType || '';
    return c.join(COMP);            // holes join as empty components
}

// ---------------------------------------------------------------------------

var SENDING_APP   = globalMap.get('HISCRIBE_APP')      || 'HISCRIBE';
var SENDING_FAC   = globalMap.get('HISCRIBE_FACILITY') || 'HISCRIBE_DEV';
var RECEIVING_APP = globalMap.get('PM_APP')            || 'PM_MOCK';
var RECEIVING_FAC = globalMap.get('PM_FACILITY')       || 'MEMORIAL_SIM';

var raw = connectorMessage.getRawData();
var bundle;
try {
    bundle = JSON.parse(raw);
} catch (e) {
    logger.error('[Charge_Outbound] Body is not JSON: ' + e);
    throw new Error('Charge_Outbound expected a FHIR Bundle as JSON: ' + e);
}

var chargeItems  = collect(bundle, 'ChargeItem');
var conditions   = collect(bundle, 'Condition');
var patient      = collect(bundle, 'Patient')[0] || null;
var practitioner = collect(bundle, 'Practitioner')[0] || null;

if (!chargeItems.length) {
    logger.error('[Charge_Outbound] Bundle contains no ChargeItem');
    throw new Error('Bundle contains no ChargeItem resource');
}

var sessionId = httpHeader('X-HiScribe-Session') || 'UNKNOWN';
var mrn = identifierValue(patient, 'mrn');
var npi = identifierValue(practitioner, 'us-npi');
var when = ts(chargeItems[0].occurrenceDateTime);

// Resolve the primary billing diagnosis once; every FT1 references it.
var primaryIcd10 = null;
for (var c = 0; c < conditions.length; c++) {
    var icd = codingBySystem(conditions[c].code, ICD10_SYSTEMS);
    if (icd) { primaryIcd10 = icd; break; }
}
if (!primaryIcd10 && conditions.length) {
    var snomedOnly = codingBySystem(conditions[0].code, SNOMED_SYSTEMS);
    logger.warn('[Charge_Outbound] Condition has ' +
                (snomedOnly ? 'only a SNOMED coding (' + snomedOnly.code + ')' : 'no usable coding') +
                ' — FT1-19 will be empty. A claim needs ICD-10-CM.');
}

var segments = [];

segments.push([
    'MSH', '^~\\&', SENDING_APP, SENDING_FAC, RECEIVING_APP, RECEIVING_FAC,
    when, '', 'DFT^P03^DFT_P03', esc(sessionId), 'T', '2.5'
].join(FIELD));

segments.push(['EVN', 'P03', when].join(FIELD));

segments.push([
    'PID', '1', '', esc(mrn) + '^^^' + SENDING_FAC + '^MR', '', '', '', '', ''
].join(FIELD));

segments.push([
    'PV1', '1', 'O', '', '', '', '', xcn(esc(npi), '', '', 'NPI')
].join(FIELD));

var ft1Count = 0;
for (var i = 0; i < chargeItems.length; i++) {
    var item = chargeItems[i];

    // Only provider-confirmed charges may be billed. HiScribe gates E/M level
    // selection behind explicit provider confirmation because it is a billing
    // determination with legal and financial consequence; an unconfirmed
    // ChargeItem reaching this point is a bug upstream, not something to
    // quietly bill.
    if (item.status !== 'billable') {
        logger.warn('[Charge_Outbound] Skipping ChargeItem ' + item.id +
                    ' with status "' + item.status + '" — only "billable" is posted');
        continue;
    }

    var procedure = codingBySystem(item.code, ['cpt', 'hcpcs']) ||
                    ((item.code && item.code.coding && item.code.coding[0]) || null);
    if (!procedure) {
        logger.error('[Charge_Outbound] ChargeItem ' + item.id + ' has no procedure code');
        continue;
    }

    ft1Count++;
    var quantity = (item.quantity && item.quantity.value) || 1;

    var ft1 = [];
    ft1[0]  = 'FT1';
    ft1[1]  = String(ft1Count);                       // FT1-1  Set ID
    ft1[2]  = esc(item.id || (sessionId + '-' + ft1Count));  // FT1-2  Transaction ID
    ft1[3]  = '';
    ft1[4]  = when;                                   // FT1-4  Transaction Date
    ft1[5]  = when;                                   // FT1-5  Posting Date
    ft1[6]  = 'CG';                                   // FT1-6  Type (0017) Charge
    ft1[7]  = ce(procedure, 'C4');                    // FT1-7  Transaction Code
    ft1[8]  = esc(procedure.display || '');           // FT1-8  Description
    ft1[9]  = '';
    ft1[10] = String(quantity);                       // FT1-10 Quantity
    ft1[11] = '';                                     // FT1-11 Amount — priced by the PM system
    ft1[12] = '';
    ft1[13] = '';
    ft1[14] = '';
    ft1[15] = '';
    ft1[16] = '';
    ft1[17] = '';
    ft1[18] = '';
    ft1[19] = ce(primaryIcd10, 'I10');                // FT1-19 Diagnosis (ICD-10-CM)
    ft1[20] = xcn(esc(npi), '', '', 'NPI');               // FT1-20 Performed By
    ft1[21] = '';
    ft1[22] = '';
    ft1[23] = '';
    ft1[24] = '';
    ft1[25] = ce(procedure, 'C4');                    // FT1-25 Procedure Code
    segments.push(ft1.join(FIELD));
}

if (ft1Count === 0) {
    logger.error('[Charge_Outbound] No billable ChargeItem in bundle for session ' + sessionId);
    throw new Error('no billable charges to post');
}

// DG1 repetitions carry the diagnosis list. ICD-10-CM again, for the same
// reason as FT1-19 — this is the claim, not the chart.
var dg1Count = 0;
for (var d = 0; d < conditions.length; d++) {
    var coding = codingBySystem(conditions[d].code, ICD10_SYSTEMS);
    if (!coding) continue;
    dg1Count++;
    segments.push([
        'DG1', String(dg1Count), 'I10', ce(coding, 'I10'),
        esc(coding.display || ''), when,
        // DG1-6 Diagnosis Type, table 0052: A = admitting, W = working, F = final.
        // Every diagnosis on a posted charge is final; 'A' does not mean
        // "secondary" and would misdescribe a confirmed diagnosis as provisional.
        // Ordering (DG1-1) is what distinguishes primary from secondary.
        'F'
    ].join(FIELD));
}

var hl7 = segments.join('\r') + '\r';

logger.info('[Charge_Outbound] session=' + sessionId + ' ft1=' + ft1Count +
            ' dg1=' + dg1Count + ' icd10=' + (primaryIcd10 ? primaryIcd10.code : 'MISSING') +
            ' bytes=' + hl7.length);

channelMap.put('hl7Message', hl7);
channelMap.put('sessionId', sessionId);
return;
