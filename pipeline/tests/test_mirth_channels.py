"""Structural tests for the generated Mirth channel XML.

These exist because of one specific Mirth behaviour: a channel containing an
element name that does not match a field on the connector properties class is
accepted with HTTP 200 and then stored with the entire connector SILENTLY
DISCARDED. The only symptom is that the channel's description is rewritten to
"This channel is invalid" and it refuses to deploy.

Catching that in CI is much cheaper than catching it against a running server,
so the checks below assert the field names that were verified against the
classes inside nextgenhealthcare/connect:4.4.2.
"""

import glob
import os
import pytest
from defusedxml import ElementTree as ET

CHANNEL_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'mirth', 'channels')
)
CHANNEL_FILES = sorted(glob.glob(os.path.join(CHANNEL_DIR, '*.xml')))

EXPECTED = {'ADT_Inbound', 'Charge_Outbound', 'EHR_Mock', 'Note_Outbound', 'PM_Mock'}


def _tree(path):
    return ET.parse(path).getroot()


def test_channel_files_exist():
    assert CHANNEL_FILES, f'no channel XML in {CHANNEL_DIR} — run build_channels.py'
    names = {_tree(p).findtext('name') for p in CHANNEL_FILES}
    assert names == EXPECTED


@pytest.mark.parametrize('path', CHANNEL_FILES, ids=lambda p: os.path.basename(p))
def test_channel_is_well_formed(path):
    root = _tree(path)
    assert root.tag == 'channel'
    assert root.findtext('id')
    assert root.findtext('name')


@pytest.mark.parametrize('path', CHANNEL_FILES, ids=lambda p: os.path.basename(p))
def test_channel_is_enabled(path):
    """Without exportData/metadata/enabled a channel imports DISABLED, and
    deploying a disabled channel returns 204 while doing nothing at all."""
    root = _tree(path)
    assert root.findtext('exportData/metadata/enabled') == 'true'


@pytest.mark.parametrize('path', CHANNEL_FILES, ids=lambda p: os.path.basename(p))
def test_connectors_survived_generation(path):
    root = _tree(path)
    assert root.find('sourceConnector/properties') is not None
    assert root.findtext('sourceConnector/transportName')
    destinations = root.findall('destinationConnectors/connector')
    assert destinations, 'channel has no destination connector'
    for dest in destinations:
        assert dest.findtext('transportName')


@pytest.mark.parametrize('path', CHANNEL_FILES, ids=lambda p: os.path.basename(p))
def test_source_has_resource_ids(path):
    """A null sourceConnectorProperties.resourceIds imports fine and then throws
    NullPointerException at deploy time."""
    root = _tree(path)
    props = root.find('.//sourceConnectorProperties/resourceIds')
    assert props is not None, 'sourceConnectorProperties is missing resourceIds'


@pytest.mark.parametrize('path', CHANNEL_FILES, ids=lambda p: os.path.basename(p))
def test_message_storage_mode_is_set(path):
    """A null messageStorageMode deploys with a NullPointerException."""
    assert _tree(path).findtext('properties/messageStorageMode')


@pytest.mark.parametrize('path', CHANNEL_FILES, ids=lambda p: os.path.basename(p))
def test_no_invalid_field_names(path):
    """Guards the exact field names that silently invalidated a connector."""
    with open(path, encoding='utf-8') as fh:
        xml = fh.read()
    # MLLPModeProperties' field is maxRetries.
    assert '<maxRetryCount>' not in xml
    # DestinationConnectorProperties' field is reattachAttachments.
    assert '<updateAttachment>' not in xml
    # There is no FileSchemeProperties class; only FTP, Sftp and Smb have one.
    assert 'FileSchemeProperties' not in xml
    # HttpReceiverProperties' flag is useResponseHeadersVariable; the dispatcher's
    # is useHeadersVariable. They are not interchangeable.
    if 'HttpReceiverProperties' in xml:
        assert '<useHeadersVariable>' not in xml


@pytest.mark.parametrize('path', CHANNEL_FILES, ids=lambda p: os.path.basename(p))
def test_hl7_datatypes_are_fully_populated(path):
    """HL7v2DataTypeProperties with a null serializationProperties imports and
    then fails to deploy."""
    with open(path, encoding='utf-8') as fh:
        xml = fh.read()
    if 'HL7v2DataTypeProperties' in xml:
        assert 'HL7v2SerializationProperties' in xml
        assert 'HL7v2ResponseGenerationProperties' in xml


def test_mllp_framing_bytes_are_standard():
    """MLLP is <VT> message <FS><CR> — 0x0B ... 0x1C 0x0D."""
    for path in CHANNEL_FILES:
        with open(path, encoding='utf-8') as fh:
            xml = fh.read()
        if 'MLLPModeProperties' in xml:
            assert '<startOfMessageBytes>0B</startOfMessageBytes>' in xml
            assert '<endOfMessageBytes>1C0D</endOfMessageBytes>' in xml


def test_outbound_channels_return_the_downstream_ack():
    """An HTTP 200 from Mirth only proves Mirth accepted the bundle. The caller
    needs the real MSA to know the receiving system committed it."""
    for name in ('Note_Outbound', 'Charge_Outbound'):
        path = os.path.join(CHANNEL_DIR, f'{name}.xml')
        root = _tree(path)
        assert root.findtext('.//sourceConnectorProperties/responseVariable') == 'Postprocessor'
        assert 'responseMap.get' in (root.findtext('postprocessingScript') or '')


def test_adt_inbound_filters_rather_than_errors():
    """Unsupported ADT events must be FILTERED, not dispatched with an empty
    body and recorded as errors — which is what the first version did."""
    root = _tree(os.path.join(CHANNEL_DIR, 'ADT_Inbound.xml'))
    rule = root.find('sourceConnector/filter/elements/'
                     'com.mirth.connect.plugins.javascriptrule.JavaScriptRule')
    assert rule is not None, 'ADT_Inbound has no source filter rule'
    assert 'return false' in (rule.findtext('script') or '')
    # A filtered ADT event is acknowledged AA, not AR: the upstream engine must
    # not retry an event this channel deliberately ignores.
    code = root.findtext('sourceConnector/transformer/inboundProperties/'
                         'responseGenerationProperties/rejectedACKCode')
    assert code == 'AA', f'ADT_Inbound answers filtered messages with {code}, expected AA'


def test_xcn_identifier_type_is_component_13():
    """'NPI' belongs in XCN-13 (Identifier Type Code), not XCN-9 (Assigning
    Authority). Eight carets put it in 9; that was an earlier defect."""
    for name in ('Note_Outbound', 'Charge_Outbound'):
        with open(os.path.join(CHANNEL_DIR, f'{name}.xml'), encoding='utf-8') as fh:
            xml = fh.read()
        assert "'^^^^^^^^NPI'" not in xml, f'{name} still places NPI in XCN-9'
        assert 'c[12] = identifierType' in xml, f'{name} lacks the by-index XCN builder'


def test_transformers_are_inlined():
    """The mapping logic must actually reach the channel, not just exist on disk."""
    for name, marker in (('Note_Outbound', 'MDM^T02'),
                         ('Charge_Outbound', 'DFT^P03'),
                         ('ADT_Inbound', 'patientContext')):
        with open(os.path.join(CHANNEL_DIR, f'{name}.xml'), encoding='utf-8') as fh:
            xml = fh.read()
        assert 'JavaScriptStep' in xml, f'{name} has no transformer step'
        assert marker in xml, f'{name} transformer does not mention {marker}'
