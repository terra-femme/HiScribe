/**
 * ADT_Inbound source transformer — HL7 v2 ADT -> patient-context JSON.
 *
 * This is the inbound half of the interface. A registration/ADT feed tells
 * HiScribe who the patient is before the encounter is recorded, so the
 * clinician is not retyping an MRN that the source system already knows.
 *
 * Accepts A01 (admit), A04 (register) and A08 (update). They carry the same
 * PID/PV1 payload for this purpose; treating A08 as an update rather than
 * ignoring it is what keeps demographics from going stale mid-encounter.
 *
 * The message arrives with inbound data type HL7V2, so Mirth exposes it as E4X
 * XML in `msg`. Field access is by the standard's own coordinates, which keeps
 * this readable against the spec rather than against a positional split.
 */

/** Safe E4X read — a missing segment or field must yield '' rather than throw. */
function get(path) {
    try {
        var v = path();
        if (v === undefined || v === null) return '';
        var s = v.toString();
        return s === 'undefined' ? '' : s;
    } catch (e) {
        return '';
    }
}

var triggerEvent = get(function () { return msg['MSH']['MSH.9']['MSH.9.2']; });
var controlId    = get(function () { return msg['MSH']['MSH.10']['MSH.10.1']; });

var ACCEPTED = { 'A01': 1, 'A04': 1, 'A08': 1 };
if (!ACCEPTED[triggerEvent]) {
    logger.warn('[ADT_Inbound] Ignoring unsupported trigger event ' + triggerEvent +
                ' (control id ' + controlId + ')');
    // Filtering here rather than erroring: an ADT feed carries many event types
    // and a scribe has no business reacting to most of them. This is a normal
    // outcome, not a failure.
    channelMap.put('skip', true);
    return;
}

// PID-3 is the patient identifier list. Real feeds put several identifier types
// in it, so the MR (medical record number, table 0203) entry is selected by
// type rather than assuming the first repetition is the MRN.
var mrn = '', assigningAuthority = '';
try {
    var ids = msg['PID']['PID.3'];
    for (var i = 0; i < ids.length(); i++) {
        var idType = get(function () { return ids[i]['PID.3.5']; });
        if (idType === 'MR' || (idType === '' && mrn === '')) {
            mrn = get(function () { return ids[i]['PID.3.1']; });
            assigningAuthority = get(function () { return ids[i]['PID.3.4']; });
            if (idType === 'MR') break;
        }
    }
} catch (e) {
    logger.error('[ADT_Inbound] Could not read PID-3: ' + e);
}

var context = {
    mrn:                mrn,
    assigningAuthority: assigningAuthority,
    familyName:         get(function () { return msg['PID']['PID.5']['PID.5.1']; }),
    givenName:          get(function () { return msg['PID']['PID.5']['PID.5.2']; }),
    birthDate:          get(function () { return msg['PID']['PID.7']['PID.7.1']; }),
    administrativeSex:  get(function () { return msg['PID']['PID.8']['PID.8.1']; }),
    patientClass:       get(function () { return msg['PV1']['PV1.2']['PV1.2.1']; }),
    attendingNpi:       get(function () { return msg['PV1']['PV1.7']['PV1.7.1']; }),
    attendingFamily:    get(function () { return msg['PV1']['PV1.7']['PV1.7.2']; }),
    visitNumber:        get(function () { return msg['PV1']['PV1.19']['PV1.19.1']; }),
    triggerEvent:       triggerEvent,
    messageControlId:   controlId
};

if (!context.mrn) {
    // No MRN means there is nothing to key patient context on. Better to reject
    // loudly than to write a context row that can never be matched.
    logger.error('[ADT_Inbound] ' + triggerEvent + ' ' + controlId + ' has no MRN in PID-3');
    throw new Error('ADT message carries no medical record number');
}

logger.info('[ADT_Inbound] ' + triggerEvent + ' control=' + controlId +
            ' mrn=' + context.mrn + ' class=' + context.patientClass +
            ' npi=' + (context.attendingNpi || 'none'));

channelMap.put('patientContext', JSON.stringify(context));
channelMap.put('mrn', context.mrn);
return;
