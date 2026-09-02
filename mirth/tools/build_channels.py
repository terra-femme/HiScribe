"""Generate the Mirth channel XML in `mirth/channels/` from the specs below.

Why generate instead of hand-editing XML
----------------------------------------
A Mirth channel export is roughly 350 lines, of which about 300 are the same
boilerplate every channel needs: data type properties nested five deep, resource
id maps, queue settings. Hand-maintaining five copies of that guarantees they
drift, and the interesting part — the mapping logic — ends up buried inside XML
text nodes where it cannot be read, diffed, or linted.

So the mapping logic lives in `mirth/transformers/*.js` as real JavaScript
files, and this script inlines them into channel XML. The generated XML is
committed and is importable into any Mirth 4.4 instance exactly as an
Administrator export would be.

Run after editing any transformer:

    python mirth/tools/build_channels.py
    python mirth/tools/deploy_channels.py

Field names below were read off the connector property classes inside the
running nextgenhealthcare/connect:4.4.2 image, not recalled. Mirth accepts a
channel containing an unknown element with HTTP 200 and then silently discards
the whole connector, so every name here is load-bearing.
"""

from __future__ import annotations

import os
import xml.sax.saxutils as saxutils

HERE = os.path.dirname(os.path.abspath(__file__))
MIRTH_DIR = os.path.dirname(HERE)
CHANNEL_DIR = os.path.join(MIRTH_DIR, 'channels')
TRANSFORMER_DIR = os.path.join(MIRTH_DIR, 'transformers')

V = '4.4.2'
DEFAULT_RESOURCE = (
    '<resourceIds class="linked-hash-map">'
    '<entry><string>Default Resource</string><string>[Default Resource]</string></entry>'
    '</resourceIds>'
)


def _hl7_datatype(tag: str, filtered_ack: str = 'AR') -> str:
    """The HL7 v2 data type block.

    Every nested properties object must be present. A null `serializationProperties`
    imports cleanly and then throws NullPointerException at deploy time.

    `filtered_ack` is the MSA-1 code Mirth returns for a message a filter rule
    rejected — it reuses the "rejected" slot for that. The default AR
    (Application Reject) is wrong for an inbound feed that deliberately ignores
    most event types: an upstream engine reads AR as "retry or alarm". AA says
    what is true — received and understood, not ours to act on.
    """
    p = 'com.mirth.connect.plugins.datatypes.hl7v2'
    return f'''<{tag} class="{p}.HL7v2DataTypeProperties" version="{V}">
          <serializationProperties class="{p}.HL7v2SerializationProperties" version="{V}">
            <handleRepetitions>true</handleRepetitions>
            <handleSubcomponents>true</handleSubcomponents>
            <useStrictParser>false</useStrictParser>
            <useStrictValidation>false</useStrictValidation>
            <stripNamespaces>false</stripNamespaces>
            <segmentDelimiter>\\r</segmentDelimiter>
            <convertLineBreaks>true</convertLineBreaks>
          </serializationProperties>
          <deserializationProperties class="{p}.HL7v2DeserializationProperties" version="{V}">
            <useStrictParser>false</useStrictParser>
            <useStrictValidation>false</useStrictValidation>
            <segmentDelimiter>\\r</segmentDelimiter>
          </deserializationProperties>
          <batchProperties class="{p}.HL7v2BatchProperties" version="{V}">
            <splitType>MSH_Segment</splitType>
            <batchScript></batchScript>
          </batchProperties>
          <responseGenerationProperties class="{p}.HL7v2ResponseGenerationProperties" version="{V}">
            <segmentDelimiter>\\r</segmentDelimiter>
            <successfulACKCode>AA</successfulACKCode>
            <successfulACKMessage></successfulACKMessage>
            <errorACKCode>AE</errorACKCode>
            <errorACKMessage>An error occurred processing the message.</errorACKMessage>
            <rejectedACKCode>{filtered_ack}</rejectedACKCode>
            <rejectedACKMessage>{'' if filtered_ack == 'AA' else 'Message rejected.'}</rejectedACKMessage>
            <dateFormat>yyyyMMddHHmmss.SSS</dateFormat>
          </responseGenerationProperties>
          <responseValidationProperties class="{p}.HL7v2ResponseValidationProperties" version="{V}">
            <successfulACKCode>AA,CA</successfulACKCode>
            <errorACKCode>AE,CE</errorACKCode>
            <rejectedACKCode>AR,CR</rejectedACKCode>
            <validateMessageControlId>true</validateMessageControlId>
            <originalMessageControlId>Destination_Encoded</originalMessageControlId>
            <originalIdMapVariable></originalIdMapVariable>
          </responseValidationProperties>
        </{tag}>'''


def _raw_datatype(tag: str) -> str:
    p = 'com.mirth.connect.plugins.datatypes.raw'
    return f'''<{tag} class="{p}.RawDataTypeProperties" version="{V}">
          <batchProperties class="{p}.RawBatchProperties" version="{V}">
            <splitType>JavaScript</splitType>
            <batchScript></batchScript>
          </batchProperties>
        </{tag}>'''


def _datatype(kind: str, tag: str, filtered_ack: str = 'AR') -> str:
    return _hl7_datatype(tag, filtered_ack) if kind == 'HL7V2' else _raw_datatype(tag)


def _filter(script_file: str | None) -> str:
    """A source filter, optionally carrying one JavaScript rule.

    A rule returning false marks the message FILTERED — counted as such in
    channel statistics and never dispatched. That is the correct outcome for an
    event the channel does not handle; a transformer cannot achieve it.
    """
    if not script_file:
        return f'''<filter version="{V}">
      <elements/>
    </filter>'''
    path = os.path.join(TRANSFORMER_DIR, script_file)
    with open(path, encoding='utf-8') as f:
        script = f.read()
    return f'''<filter version="{V}">
      <elements>
        <com.mirth.connect.plugins.javascriptrule.JavaScriptRule version="{V}">
          <name>Accept only handled trigger events</name>
          <sequenceNumber>0</sequenceNumber>
          <enabled>true</enabled>
          <operator>NONE</operator>
          <script>{saxutils.escape(script)}</script>
        </com.mirth.connect.plugins.javascriptrule.JavaScriptRule>
      </elements>
    </filter>'''


def _transformer(inbound: str, outbound: str, script_file: str | None,
                 step_name: str = 'Transform', filtered_ack: str = 'AR') -> str:
    """A transformer, optionally carrying one JavaScript step."""
    if script_file:
        path = os.path.join(TRANSFORMER_DIR, script_file)
        with open(path, encoding='utf-8') as f:
            script = f.read()
        elements = f'''<elements>
          <com.mirth.connect.plugins.javascriptstep.JavaScriptStep version="{V}">
            <name>{step_name}</name>
            <sequenceNumber>0</sequenceNumber>
            <enabled>true</enabled>
            <script>{saxutils.escape(script)}</script>
          </com.mirth.connect.plugins.javascriptstep.JavaScriptStep>
        </elements>'''
    else:
        elements = '<elements/>'
    return f'''<transformer version="{V}">
        {elements}
        <inboundDataType>{inbound}</inboundDataType>
        <outboundDataType>{outbound}</outboundDataType>
        {_datatype(inbound, 'inboundProperties', filtered_ack)}
        {_datatype(outbound, 'outboundProperties', filtered_ack)}
      </transformer>'''


def _response_transformer(kind: str = 'HL7V2') -> str:
    return f'''<responseTransformer version="{V}">
        <elements/>
        <inboundDataType>{kind}</inboundDataType>
        <outboundDataType>{kind}</outboundDataType>
        {_datatype(kind, 'inboundProperties')}
        {_datatype(kind, 'outboundProperties')}
      </responseTransformer>'''


MLLP = f'''<transmissionModeProperties class="com.mirth.connect.plugins.mllpmode.MLLPModeProperties">
        <pluginPointName>MLLP</pluginPointName>
        <startOfMessageBytes>0B</startOfMessageBytes>
        <endOfMessageBytes>1C0D</endOfMessageBytes>
        <useMLLPv2>false</useMLLPv2>
        <ackBytes>06</ackBytes>
        <nackBytes>15</nackBytes>
        <maxRetries>2</maxRetries>
      </transmissionModeProperties>'''


def _source_props(response_variable: str) -> str:
    return f'''<sourceConnectorProperties version="{V}">
        <responseVariable>{response_variable}</responseVariable>
        <respondAfterProcessing>true</respondAfterProcessing>
        <processBatch>false</processBatch>
        <firstResponse>false</firstResponse>
        <processingThreads>1</processingThreads>
        <queueBufferSize>1000</queueBufferSize>
        {DEFAULT_RESOURCE}
      </sourceConnectorProperties>'''


def _dest_props() -> str:
    return f'''<destinationConnectorProperties version="{V}">
          <queueEnabled>false</queueEnabled>
          <sendFirst>false</sendFirst>
          <retryIntervalMillis>10000</retryIntervalMillis>
          <regenerateTemplate>false</regenerateTemplate>
          <retryCount>0</retryCount>
          <rotate>false</rotate>
          <includeFilterTransformer>false</includeFilterTransformer>
          <threadCount>1</threadCount>
          <threadAssignmentVariable></threadAssignmentVariable>
          <validateResponse>false</validateResponse>
          {DEFAULT_RESOURCE}
          <queueBufferSize>1000</queueBufferSize>
          <reattachAttachments>true</reattachAttachments>
        </destinationConnectorProperties>'''


# ── Source connectors ────────────────────────────────────────────────────────

def mllp_listener(port: int, response_variable: str) -> tuple[str, str]:
    props = f'''<properties class="com.mirth.connect.connectors.tcp.TcpReceiverProperties" version="{V}">
      <pluginProperties/>
      <listenerConnectorProperties version="{V}">
        <host>0.0.0.0</host>
        <port>{port}</port>
      </listenerConnectorProperties>
      {_source_props(response_variable)}
      {MLLP}
      <serverMode>true</serverMode>
      <remoteAddress></remoteAddress>
      <remotePort>0</remotePort>
      <overrideLocalBinding>false</overrideLocalBinding>
      <reconnectInterval>5000</reconnectInterval>
      <receiveTimeout>0</receiveTimeout>
      <bufferSize>65536</bufferSize>
      <maxConnections>10</maxConnections>
      <keepConnectionOpen>true</keepConnectionOpen>
      <dataTypeBinary>false</dataTypeBinary>
      <charsetEncoding>UTF-8</charsetEncoding>
      <respondOnNewConnection>0</respondOnNewConnection>
      <responseAddress></responseAddress>
      <responsePort>0</responsePort>
    </properties>'''
    return props, 'TCP Listener'


def http_listener(port: int, context_path: str, response_variable: str) -> tuple[str, str]:
    props = f'''<properties class="com.mirth.connect.connectors.http.HttpReceiverProperties" version="{V}">
      <pluginProperties/>
      <listenerConnectorProperties version="{V}">
        <host>0.0.0.0</host>
        <port>{port}</port>
      </listenerConnectorProperties>
      {_source_props(response_variable)}
      <xmlBody>false</xmlBody>
      <parseMultipart>false</parseMultipart>
      <includeMetadata>false</includeMetadata>
      <binaryMimeTypes>application/.*(?&lt;!json|xml)$|image/.*|video/.*|audio/.*</binaryMimeTypes>
      <binaryMimeTypesRegex>true</binaryMimeTypesRegex>
      <responseContentType>text/plain</responseContentType>
      <responseDataTypeBinary>false</responseDataTypeBinary>
      <responseStatusCode></responseStatusCode>
      <responseHeaders class="linked-hash-map"/>
      <responseHeadersVariable></responseHeadersVariable>
      <!-- The receiver's flag is useResponseHeadersVariable. The dispatcher's
           equivalent is useHeadersVariable; they are not interchangeable. -->
      <useResponseHeadersVariable>false</useResponseHeadersVariable>
      <charset>UTF-8</charset>
      <contextPath>{context_path}</contextPath>
      <timeout>30000</timeout>
      <staticResources/>
    </properties>'''
    return props, 'HTTP Listener'


# ── Destination connectors ───────────────────────────────────────────────────

def file_writer(directory: str, pattern: str, template: str) -> tuple[str, str]:
    props = f'''<properties class="com.mirth.connect.connectors.file.FileDispatcherProperties" version="{V}">
        <pluginProperties/>
        {_dest_props()}
        <scheme>FILE</scheme>
        <host>{directory}</host>
        <outputPattern>{pattern}</outputPattern>
        <anonymous>true</anonymous>
        <username>anonymous</username>
        <password>anonymous</password>
        <timeout>10000</timeout>
        <keepConnectionOpen>true</keepConnectionOpen>
        <maxIdleTime>0</maxIdleTime>
        <secure>true</secure>
        <passive>true</passive>
        <validateConnection>true</validateConnection>
        <outputAppend>false</outputAppend>
        <errorOnExists>false</errorOnExists>
        <temporary>false</temporary>
        <binary>false</binary>
        <charsetEncoding>UTF-8</charsetEncoding>
        <template>{saxutils.escape(template)}</template>
      </properties>'''
    return props, 'File Writer'


def mllp_sender(host: str, port: int, template: str) -> tuple[str, str]:
    props = f'''<properties class="com.mirth.connect.connectors.tcp.TcpDispatcherProperties" version="{V}">
        <pluginProperties/>
        {_dest_props()}
        {MLLP}
        <remoteAddress>{host}</remoteAddress>
        <remotePort>{port}</remotePort>
        <overrideLocalBinding>false</overrideLocalBinding>
        <localAddress>0.0.0.0</localAddress>
        <localPort>0</localPort>
        <sendTimeout>5000</sendTimeout>
        <bufferSize>65536</bufferSize>
        <maxConnections>10</maxConnections>
        <keepConnectionOpen>false</keepConnectionOpen>
        <checkRemoteHost>false</checkRemoteHost>
        <responseTimeout>30000</responseTimeout>
        <ignoreResponse>false</ignoreResponse>
        <queueOnResponseTimeout>true</queueOnResponseTimeout>
        <dataTypeBinary>false</dataTypeBinary>
        <charsetEncoding>UTF-8</charsetEncoding>
        <template>{saxutils.escape(template)}</template>
        <serverMode>false</serverMode>
      </properties>'''
    return props, 'TCP Sender'


def http_sender(url: str, method: str, content: str, content_type: str) -> tuple[str, str]:
    props = f'''<properties class="com.mirth.connect.connectors.http.HttpDispatcherProperties" version="{V}">
        <pluginProperties/>
        {_dest_props()}
        <host>{url}</host>
        <useProxyServer>false</useProxyServer>
        <proxyAddress></proxyAddress>
        <proxyPort></proxyPort>
        <method>{method}</method>
        <headers class="linked-hash-map"/>
        <parameters class="linked-hash-map"/>
        <useHeadersVariable>false</useHeadersVariable>
        <headersVariable></headersVariable>
        <useParametersVariable>false</useParametersVariable>
        <parametersVariable></parametersVariable>
        <responseXmlBody>false</responseXmlBody>
        <responseParseMultipart>false</responseParseMultipart>
        <responseIncludeMetadata>false</responseIncludeMetadata>
        <responseBinaryMimeTypes>application/.*(?&lt;!json|xml)$|image/.*|video/.*|audio/.*</responseBinaryMimeTypes>
        <responseBinaryMimeTypesRegex>true</responseBinaryMimeTypesRegex>
        <multipart>false</multipart>
        <useAuthentication>false</useAuthentication>
        <authenticationType>Basic</authenticationType>
        <usePreemptiveAuthentication>false</usePreemptiveAuthentication>
        <username></username>
        <password></password>
        <content>{saxutils.escape(content)}</content>
        <contentType>{content_type}</contentType>
        <dataTypeBinary>false</dataTypeBinary>
        <charset>UTF-8</charset>
        <socketTimeout>30000</socketTimeout>
      </properties>'''
    return props, 'HTTP Sender'


# ── Channel assembly ─────────────────────────────────────────────────────────

def build_channel(cid, name, description, source, dest, *,
                  source_kinds=('HL7V2', 'HL7V2'),
                  dest_kinds=('HL7V2', 'HL7V2'),
                  source_script=None, source_step='Transform', source_filter=None,
                  filtered_ack='AR',
                  dest_name='destination', response_kind='HL7V2',
                  postprocessor='return;') -> str:
    src_props, src_transport = source
    dst_props, dst_transport = dest
    return f'''<channel version="{V}">
  <id>{cid}</id>
  <nextMetaDataId>2</nextMetaDataId>
  <name>{name}</name>
  <description>{saxutils.escape(description)}</description>
  <revision>1</revision>
  <sourceConnector version="{V}">
    <metaDataId>0</metaDataId>
    <name>sourceConnector</name>
    {src_props}
    {_transformer(source_kinds[0], source_kinds[1], source_script, source_step, filtered_ack)}
    {_filter(source_filter)}
    <transportName>{src_transport}</transportName>
    <mode>SOURCE</mode>
    <enabled>true</enabled>
    <waitForPrevious>true</waitForPrevious>
  </sourceConnector>
  <destinationConnectors>
    <connector version="{V}">
      <metaDataId>1</metaDataId>
      <name>{dest_name}</name>
      {dst_props}
      {_transformer(dest_kinds[0], dest_kinds[1], None)}
      {_response_transformer(response_kind)}
      <filter version="{V}">
        <elements/>
      </filter>
      <transportName>{dst_transport}</transportName>
      <mode>DESTINATION</mode>
      <enabled>true</enabled>
      <waitForPrevious>true</waitForPrevious>
    </connector>
  </destinationConnectors>
  <preprocessingScript>return message;</preprocessingScript>
  <postprocessingScript>{saxutils.escape(postprocessor)}</postprocessingScript>
  <deployScript>return;</deployScript>
  <undeployScript>return;</undeployScript>
  <properties version="{V}">
    <clearGlobalChannelMap>true</clearGlobalChannelMap>
    <messageStorageMode>DEVELOPMENT</messageStorageMode>
    <encryptData>false</encryptData>
    <encryptAttachments>false</encryptAttachments>
    <encryptCustomMetaData>false</encryptCustomMetaData>
    <removeContentOnCompletion>false</removeContentOnCompletion>
    <removeOnlyFilteredOnCompletion>false</removeOnlyFilteredOnCompletion>
    <removeAttachmentsOnCompletion>false</removeAttachmentsOnCompletion>
    <initialState>STARTED</initialState>
    <storeAttachments>true</storeAttachments>
    <metaDataColumns/>
    <attachmentProperties version="{V}">
      <type>None</type>
      <properties/>
    </attachmentProperties>
    {DEFAULT_RESOURCE}
  </properties>
  <exportData>
    <metadata>
      <enabled>true</enabled>
    </metadata>
    <dependentIds/>
    <dependencyIds/>
    <channelTags/>
  </exportData>
</channel>
'''


def ack_postprocessor(dest_name: str, channel: str) -> str:
    """Return the downstream ACK as the channel's HTTP response body.

    The source response variable is set to "Postprocessor", so whatever this
    script returns becomes the response the caller receives.

    This matters more than it looks. An HTTP 200 from Mirth only proves the
    interface engine accepted the bundle. It says nothing about whether the
    receiving system committed the document. Passing the real MSA back is what
    lets HiScribe tell a filed note from a lost one, which is exactly the
    failure mode that silently loses clinical documentation.
    """
    return f'''/**
 * Return the downstream ACK to the caller so delivery can be verified.
 * See ack_postprocessor() in mirth/tools/build_channels.py.
 */
var response = responseMap.get('{dest_name}');
if (response) {{
    return response.getMessage();
}}
logger.warn('[{channel}] Destination produced no response — caller cannot verify delivery');
return '';'''


SIM_NOTICE = (
    'This is a SIMULATED system for development and portfolio use. It is not '
    'Epic, Cerner, or any commercial product, and all data flowing through it '
    'is synthetic. Nothing here should be described as experience with a '
    'vendor EHR or with real patient data.'
)

CHANNELS = [
    dict(
        cid='a1000000-0000-4000-8000-000000000001',
        name='EHR_Mock',
        description=(
            'Stand-in for a receiving EHR document repository. Listens for HL7 v2 '
            'over MLLP on 6662, writes each message to disk, returns an '
            'auto-generated ACK.\n\n'
            'Built before Note_Outbound on purpose: a transformer aimed at a '
            'destination that does not exist cannot be tested, and an untested '
            'mapping is a guess.\n\n' + SIM_NOTICE
        ),
        source=lambda: mllp_listener(6662, 'Auto-generate (After source transformer)'),
        dest=lambda: file_writer('/opt/connect/appdata/ehr_inbox',
                                 '${message.messageId}_MDM_T02.hl7',
                                 '${message.rawData}'),
        dest_name='Write to EHR inbox',
    ),
    dict(
        cid='a1000000-0000-4000-8000-000000000002',
        name='PM_Mock',
        description=(
            'Stand-in for a practice-management / billing system. Listens for HL7 v2 '
            'over MLLP on 6663, writes each message to disk, returns an ACK.\n\n'
            + SIM_NOTICE
        ),
        source=lambda: mllp_listener(6663, 'Auto-generate (After source transformer)'),
        dest=lambda: file_writer('/opt/connect/appdata/pm_inbox',
                                 '${message.messageId}_DFT_P03.hl7',
                                 '${message.rawData}'),
        dest_name='Write to PM inbox',
    ),
    dict(
        cid='a1000000-0000-4000-8000-000000000003',
        name='ADT_Inbound',
        description=(
            'Inbound registration feed. Receives ADT^A01/A04/A08 over MLLP on 6661, '
            'parses PID and PV1, and POSTs patient context to the HiScribe pipeline '
            'so a clinician does not retype an MRN the source system already has.\n\n'
            'Mapping logic: mirth/transformers/adt_inbound.js\n\n' + SIM_NOTICE
        ),
        source=lambda: mllp_listener(6661, 'Auto-generate (After source transformer)'),
        source_filter='adt_inbound.filter.js',
        # Filtered events are acknowledged AA: received, not ours. See _hl7_datatype.
        filtered_ack='AA',
        source_script='adt_inbound.js',
        source_step='Parse PID/PV1 to patient context',
        dest=lambda: http_sender(
            'http://host.docker.internal:8000/fhir/patient-context',
            'post', '${patientContext}', 'application/json'),
        dest_kinds=('RAW', 'RAW'),
        dest_name='POST patient context',
        response_kind='RAW',
    ),
    dict(
        cid='a1000000-0000-4000-8000-000000000004',
        name='Note_Outbound',
        description=(
            'The centrepiece. Receives a FHIR R4B transaction Bundle over HTTP on '
            '8081/note, maps the Composition to an HL7 v2.5 MDM^T02, and forwards it '
            'to EHR_Mock over MLLP. The downstream ACK is returned to the caller so '
            'HiScribe can tell a delivered document from a lost one.\n\n'
            'Mapping logic: mirth/transformers/note_outbound_mdm.js\n\n' + SIM_NOTICE
        ),
        source=lambda: http_listener(8081, '/note', 'Postprocessor'),
        source_kinds=('RAW', 'RAW'),
        source_script='note_outbound_mdm.js',
        source_step='FHIR Composition to MDM^T02',
        dest=lambda: mllp_sender('localhost', 6662, '${hl7Message}'),
        dest_kinds=('RAW', 'RAW'),
        dest_name='Send to EHR',
        postprocessor=ack_postprocessor('Send to EHR', 'Note_Outbound'),
    ),
    dict(
        cid='a1000000-0000-4000-8000-000000000005',
        name='Charge_Outbound',
        description=(
            'Clinical documentation to revenue cycle. Receives a FHIR Bundle carrying '
            'provider-confirmed ChargeItem and dual-coded Condition resources over '
            'HTTP on 8082/charge, maps them to an HL7 v2.5 DFT^P03 with FT1 and DG1 '
            'segments, and posts to PM_Mock over MLLP.\n\n'
            'ICD-10-CM is selected for FT1-19 and DG1 deliberately: SNOMED CT carries '
            'the clinical meaning, ICD-10-CM is what a payer adjudicates.\n\n'
            'Mapping logic: mirth/transformers/charge_outbound_dft.js\n\n' + SIM_NOTICE
        ),
        source=lambda: http_listener(8082, '/charge', 'Postprocessor'),
        source_kinds=('RAW', 'RAW'),
        source_script='charge_outbound_dft.js',
        source_step='FHIR ChargeItem to DFT^P03',
        dest=lambda: mllp_sender('localhost', 6663, '${hl7Message}'),
        dest_kinds=('RAW', 'RAW'),
        dest_name='Send to PM',
        postprocessor=ack_postprocessor('Send to PM', 'Charge_Outbound'),
    ),
]


def main() -> None:
    os.makedirs(CHANNEL_DIR, exist_ok=True)
    for spec in CHANNELS:
        spec = dict(spec)
        source = spec.pop('source')()
        dest = spec.pop('dest')()
        name = spec['name']
        xml = build_channel(source=source, dest=dest, **spec)
        path = os.path.join(CHANNEL_DIR, f'{name}.xml')
        with open(path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(xml)
        print(f'wrote {os.path.relpath(path, MIRTH_DIR)} ({len(xml):,} bytes)')


if __name__ == '__main__':
    main()
