/**
 * Note_Outbound source transformer — FHIR R4B Composition -> HL7 v2.5 MDM^T02.
 *
 * This is the centrepiece mapping. HiScribe POSTs a FHIR transaction Bundle
 * here; this builds the HL7 v2 document-management message that a chart
 * actually files, and puts it on the channel map for the MLLP destination.
 *
 * Message type rationale
 * ----------------------
 * MDM^T02 is "Original Document Notification and Content" — the message a
 * transcription or documentation system sends to file a NEW document with its
 * body included. TXA carries the document header; the body travels as OBX
 * repetitions. For an ambient scribe this is the correct message in the
 * standard. (An amendment to an already-filed document would be T08, not T02.)
 *
 * Structure, HL7 v2.5 Chapter 9:
 *   MSH, [SFT], EVN, PID, PV1, [common order], TXA, {OBX/[NTE]}
 *
 * Verified against the HL7 v2.5 standard:
 *   TXA-2  Document Type              table 0270 -> PR  Progress note
 *   TXA-3  Content Presentation       table 0191 -> TX  Machine readable text
 *   TXA-17 Document Completion Status table 0271 -> LA  Legally authenticated
 *   TXA-19 Document Availability      table 0273 -> AV  Available for patient care
 *
 * The TXA-17 mapping is the one that carries real meaning. HiScribe records the
 * provider as the accountable author via Composition.attester.mode = 'legal'.
 * That is precisely what "legally authenticated" means in table 0271, so the
 * FHIR attestation and the v2 completion status stay consistent. When the
 * attestation is missing we emit AU (authenticated) rather than claiming a
 * legal attestation that was never made.
 */

var FIELD = '|', COMP = '^', REP = '~', ESC = '\\', SUB = '&';

/**
 * Escape HL7 delimiter characters in field content.
 *
 * Clinical narrative is arbitrary speech. An unescaped '|' or '^' in a
 * transcript silently shifts every following field by one position, which is
 * the classic way a v2 interface corrupts a chart without erroring.
 * The backslash must be replaced first or it would double-escape the others.
 */
function esc(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/\\/g, '\\E\\')
        .replace(/\|/g, '\\F\\')
        .replace(/\^/g, '\\S\\')
        .replace(/~/g,  '\\R\\')
        .replace(/&/g,  '\\T\\')
        // Segments are CR-delimited, so a literal newline inside a field would
        // terminate the segment. \.br\ is the HL7 formatting escape for a line
        // break and survives round-tripping.
        .replace(/\r\n|\r|\n/g, '\\.br\\');
}

/** HL7 TS format: YYYYMMDDHHMMSS, always UTC so the receiver is unambiguous. */
function ts(iso) {
    var d = iso ? new Date(iso) : new Date();
    if (isNaN(d.getTime())) d = new Date();
    function p(n) { return (n < 10 ? '0' : '') + n; }
    return d.getUTCFullYear() + p(d.getUTCMonth() + 1) + p(d.getUTCDate()) +
           p(d.getUTCHours()) + p(d.getUTCMinutes()) + p(d.getUTCSeconds());
}

/** Pull the first entry of a given resourceType out of a transaction Bundle. */
function findResource(bundle, type) {
    var entries = (bundle && bundle.entry) || [];
    for (var i = 0; i < entries.length; i++) {
        var r = entries[i].resource;
        if (r && r.resourceType === type) return r;
    }
    return null;
}

/** First identifier value, optionally filtered by system substring. */
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

/**
 * Strip the generated XHTML wrapper off a FHIR Narrative to recover the text.
 * Composition.section[].text.div is XHTML; OBX-5 wants plain text.
 */
function narrativeText(section) {
    if (!section || !section.text || !section.text.div) return '';
    return String(section.text.div)
        .replace(/<[^>]*>/g, '')
        .replace(/&lt;/g, '<').replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"').replace(/&#39;/g, "'")
        .replace(/&amp;/g, '&')
        .trim();
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
        logger.warn('[Note_Outbound] Could not read header ' + name + ': ' + e);
    }
    var direct = sourceMap.get(name);
    return (direct === null || direct === undefined) ? '' : String(direct);
}

// ---------------------------------------------------------------------------

var SENDING_APP  = globalMap.get('HISCRIBE_APP')      || 'HISCRIBE';
var SENDING_FAC  = globalMap.get('HISCRIBE_FACILITY') || 'HISCRIBE_DEV';
var RECEIVING_APP = globalMap.get('EHR_APP')          || 'EHR_MOCK';
var RECEIVING_FAC = globalMap.get('EHR_FACILITY')     || 'MEMORIAL_SIM';

var raw = connectorMessage.getRawData();
var bundle;
try {
    bundle = JSON.parse(raw);
} catch (e) {
    logger.error('[Note_Outbound] Body is not JSON: ' + e);
    throw new Error('Note_Outbound expected a FHIR Bundle as JSON: ' + e);
}

var composition  = findResource(bundle, 'Composition');
var patient      = findResource(bundle, 'Patient');
var practitioner = findResource(bundle, 'Practitioner');
var encounter    = findResource(bundle, 'Encounter');

if (!composition) {
    logger.error('[Note_Outbound] Bundle has no Composition — refusing to build MDM');
    throw new Error('Bundle contains no Composition resource');
}

// The session id travels as a header so the document in the receiving system
// can be traced back to the encounter that produced it.
var sessionId = httpHeader('X-HiScribe-Session') || composition.id || 'UNKNOWN';
var mrn = identifierValue(patient, 'mrn');
var npi = identifierValue(practitioner, 'us-npi');
var when = ts(composition.date);

if (!mrn)  logger.warn('[Note_Outbound] No MRN on Patient for session ' + sessionId);
if (!npi)  logger.warn('[Note_Outbound] No NPI on Practitioner for session ' + sessionId);

// TXA-17 follows the attestation, it is not assumed. See the header comment.
var attested = false;
if (composition.attester) {
    for (var a = 0; a < composition.attester.length; a++) {
        if (composition.attester[a].mode === 'legal') { attested = true; break; }
    }
}
var completionStatus = attested ? 'LA' : 'AU';
if (!attested) {
    logger.warn('[Note_Outbound] Composition ' + composition.id +
                ' has no legal attester — TXA-17 downgraded to AU');
}

// Encounter.class maps to PV1-2 patient class (table 0004). An ambient office
// scribe produces outpatient encounters; virtual visits are still outpatient
// for the purposes of filing a document.
var patientClass = 'O';
if (encounter && encounter.class && encounter.class.code === 'IMP') patientClass = 'I';

var segments = [];

segments.push([
    'MSH', '^~\\&', SENDING_APP, SENDING_FAC, RECEIVING_APP, RECEIVING_FAC,
    when, '', 'MDM^T02^MDM_T02', esc(sessionId),
    // 'T' = training/test. This pipeline carries synthetic data only; claiming
    // 'P' (production) would misrepresent what the interface is doing.
    'T', '2.5'
].join(FIELD).replace('MSH|^~\\&|', 'MSH|^~\\&|'));

segments.push(['EVN', 'T02', when].join(FIELD));

segments.push([
    'PID', '1', '',
    esc(mrn) + '^^^' + SENDING_FAC + '^MR',   // PID-3, MR = table 0203
    '', '', '', '', ''
].join(FIELD));

segments.push([
    'PV1', '1', patientClass, '', '', '', '', esc(npi) + '^^^^^^^^NPI'
].join(FIELD));

// TXA — Transcription Document Header. Field positions are 1-based, so index 0
// is the segment name and every field below sits where the standard puts it.
var txa = [];
txa[0]  = 'TXA';
txa[1]  = '1';                       // TXA-1  Set ID
txa[2]  = 'PR';                      // TXA-2  Document Type (0270) progress note
txa[3]  = 'TX';                      // TXA-3  Content Presentation (0191)
txa[4]  = when;                      // TXA-4  Activity Date/Time
txa[5]  = esc(npi);                  // TXA-5  Primary Activity Provider
txa[6]  = when;                      // TXA-6  Origination Date/Time
txa[7]  = when;                      // TXA-7  Transcription Date/Time
txa[8]  = '';
txa[9]  = '';
txa[10] = '';
txa[11] = '';
txa[12] = esc(composition.id || sessionId);  // TXA-12 Unique Document Number
txa[13] = '';
txa[14] = '';
txa[15] = '';
txa[16] = '';
txa[17] = completionStatus;          // TXA-17 Completion Status (0271)
txa[18] = '';
txa[19] = 'AV';                      // TXA-19 Availability Status (0273)
segments.push(txa.join(FIELD));

// One OBX per Composition.section, carrying the LOINC code the FHIR emitter
// already assigned. Re-deriving codes here would create a second source of
// truth for terminology; the mapping's job is to move them, not invent them.
var sections = composition.section || [];
var obxCount = 0;
for (var s = 0; s < sections.length; s++) {
    var text = narrativeText(sections[s]);
    if (!text) continue;
    obxCount++;

    var loinc = '', display = sections[s].title || '';
    if (sections[s].code && sections[s].code.coding && sections[s].code.coding.length) {
        loinc = sections[s].code.coding[0].code || '';
        display = sections[s].code.coding[0].display || display;
    }
    // Uncoded sections (unclassified segments, amendments) still travel. They
    // are labelled by title with no code system rather than being dropped or
    // given a code that does not describe them.
    var observationId = loinc
        ? esc(loinc) + COMP + esc(display) + COMP + 'LN'
        : esc(display);

    // Index 0 is the segment name, so 'F' must sit at index 11 to land in
    // OBX-11 (Observation Result Status). Counting from the segment name rather
    // than from OBX-1 is the classic off-by-one in hand-built v2.
    var obx = [];
    obx[0]  = 'OBX';
    obx[1]  = String(obxCount);   // OBX-1  Set ID
    obx[2]  = 'TX';               // OBX-2  Value Type
    obx[3]  = observationId;      // OBX-3  Observation Identifier
    obx[4]  = '';                 // OBX-4  Observation Sub-ID
    obx[5]  = esc(text);          // OBX-5  Observation Value
    obx[6]  = '';
    obx[7]  = '';
    obx[8]  = '';
    obx[9]  = '';
    obx[10] = '';
    obx[11] = 'F';                // OBX-11 Result Status, F = final
    segments.push(obx.join(FIELD));
}

if (obxCount === 0) {
    logger.error('[Note_Outbound] Composition ' + composition.id + ' produced no OBX');
    throw new Error('Composition has no renderable sections');
}

var hl7 = segments.join('\r') + '\r';

logger.info('[Note_Outbound] session=' + sessionId + ' mrn=' + (mrn ? 'present' : 'MISSING') +
            ' obx=' + obxCount + ' txa17=' + completionStatus + ' bytes=' + hl7.length);

channelMap.put('hl7Message', hl7);
channelMap.put('sessionId', sessionId);
return;
