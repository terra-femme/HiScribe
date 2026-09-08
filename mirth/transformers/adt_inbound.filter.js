/**
 * ADT_Inbound source FILTER — accept only the trigger events this channel handles.
 *
 * A registration feed carries dozens of event types (transfers, discharges,
 * bed swaps, merges) and a scribe has no business reacting to most of them.
 * Rejecting them here, in a filter rule, is what makes Mirth mark the message
 * FILTERED on the dashboard and in channel statistics — a normal outcome an
 * integration analyst expects to see counted, not an ERROR against the channel.
 *
 * Doing this in the transformer instead (setting a flag and returning) does not
 * stop the destination from firing: the HTTP sender would POST an empty body
 * and the message would be recorded as an error. That was the original
 * implementation, and the channel statistics proved it wrong.
 *
 * The sender still receives an ACK (MSA-1 = AA): a filtered message was
 * received and understood, it simply is not ours to act on.
 */

var ACCEPTED = { 'A01': true, 'A04': true, 'A08': true };

var triggerEvent = '';
try {
    triggerEvent = String(msg['MSH']['MSH.9']['MSH.9.2']);
} catch (e) {
    logger.warn('[ADT_Inbound] Could not read MSH-9.2: ' + e);
}

if (ACCEPTED[triggerEvent] === true) {
    return true;
}

var controlId = '';
try { controlId = String(msg['MSH']['MSH.10']['MSH.10.1']); } catch (e) {}
logger.info('[ADT_Inbound] Filtered unsupported trigger event ' + triggerEvent +
            ' (control id ' + controlId + ')');
return false;
