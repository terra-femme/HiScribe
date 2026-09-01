"""Import and deploy every channel in `mirth/channels/` into a running Mirth.

Mirth's own Administrator is a Java desktop application. This script is the
headless equivalent, so channel deployment is reproducible from a terminal and
usable in CI rather than depending on someone clicking through a GUI.

Usage
-----
    python mirth/tools/deploy_channels.py
    python mirth/tools/deploy_channels.py --url https://localhost:8443/api
    python mirth/tools/deploy_channels.py --undeploy

Three things the Mirth REST API does that are worth knowing, all learned the
hard way and all silent:

1. A channel whose XML contains an unknown element is accepted with HTTP 200,
   then stored with the offending connector STRIPPED. The only signal is that
   `description` is rewritten to "This channel is invalid." Always read the
   channel back and verify, which `_verify` below does.

2. A channel without `exportData/metadata/enabled` defaults to DISABLED, and
   deploying a disabled channel is a no-op that returns HTTP 204 with no error.

3. `POST /channels/{id}/_deploy` returns 204 whether or not anything started.
   Deployment must be confirmed by polling `/channels/statuses`.
"""

from __future__ import annotations

import argparse
import glob
import logging
import os
import re
import sys
import time
import xml.etree.ElementTree as ET

try:
    import requests
    import urllib3
except ImportError:
    sys.exit('requests is required: pip install requests')

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO, format='%(levelname)-5s %(message)s')
logger = logging.getLogger('deploy_channels')

CHANNEL_DIR = os.path.join(os.path.dirname(__file__), '..', 'channels')
DEFAULT_URL = os.environ.get('MIRTH_API_URL', 'https://localhost:8443/api')
DEFAULT_USER = os.environ.get('MIRTH_USER', 'admin')
DEFAULT_PASS = os.environ.get('MIRTH_PASSWORD', 'admin')

# Mirth blocks requests without this header as a CSRF precaution.
_HEADERS = {'X-Requested-With': 'deploy_channels'}


class Mirth:
    def __init__(self, url: str, user: str, password: str):
        self.url = url.rstrip('/')
        self.auth = (user, password)

    def _call(self, method: str, path: str, **kw) -> requests.Response:
        headers = dict(_HEADERS)
        headers.update(kw.pop('headers', {}))
        return requests.request(
            method, f'{self.url}{path}', auth=self.auth, headers=headers,
            verify=False, timeout=60, **kw
        )

    def version(self) -> str:
        return self._call('GET', '/server/version').text.strip()

    def put_channel(self, channel_xml: str, channel_id: str) -> None:
        # DELETE first so re-running is idempotent; POST on an existing id
        # updates in place but keeps the old revision, which makes it hard to
        # tell a stale channel from a fresh one.
        self._call('DELETE', f'/channels/{channel_id}')
        r = self._call('POST', '/channels', data=channel_xml.encode('utf-8'),
                       headers={'Content-Type': 'application/xml'})
        r.raise_for_status()

    def enable(self, channel_ids: list[str]) -> None:
        """Set the server-side enabled flag. Without it, deploy is a no-op."""
        entries = ''.join(
            f'<entry><string>{cid}</string>'
            f'<com.mirth.connect.model.ChannelMetadata><enabled>true</enabled>'
            f'</com.mirth.connect.model.ChannelMetadata></entry>'
            for cid in channel_ids
        )
        r = self._call('PUT', '/server/channelMetadata',
                       data=f'<map>{entries}</map>'.encode('utf-8'),
                       headers={'Content-Type': 'application/xml'})
        r.raise_for_status()

    def get_channel_xml(self, channel_id: str) -> str:
        return self._call('GET', '/channels', params={'channelId': channel_id},
                          headers={'Accept': 'application/xml'}).text

    def deploy(self, channel_id: str) -> None:
        r = self._call('POST', f'/channels/{channel_id}/_deploy',
                       params={'returnErrors': 'true'},
                       headers={'Accept': 'application/xml'})
        if r.status_code >= 400:
            detail = re.search(r'<detailMessage>(.*?)</detailMessage>', r.text, re.S)
            raise RuntimeError(detail.group(1) if detail else r.text[:400])

    def undeploy(self, channel_id: str) -> None:
        self._call('POST', f'/channels/{channel_id}/_undeploy',
                   params={'returnErrors': 'true'})

    def statuses(self) -> dict[str, str]:
        text = self._call('GET', '/channels/statuses',
                          headers={'Accept': 'application/xml'}).text
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return {}
        out = {}
        for status in root.iter('dashboardStatus'):
            name = status.findtext('name')
            state = status.findtext('state')
            if name:
                out[name] = state or 'UNKNOWN'
        return out


def _verify(mirth: Mirth, channel_id: str, name: str) -> None:
    """Confirm Mirth actually kept the connectors it was sent.

    This is the check that catches the silent-strip failure mode. An unknown
    element anywhere in a connector's properties makes XStream drop the whole
    connector while still returning HTTP 200.
    """
    stored = mirth.get_channel_xml(channel_id)
    if 'This channel is invalid' in stored:
        raise RuntimeError(
            f'{name}: Mirth stored the channel but discarded its connectors. '
            'An element name in the XML does not match a field on the '
            'connector properties class. Compare against the field list on '
            'the class inside the running image.'
        )
    if '<transportName>' not in stored:
        raise RuntimeError(f'{name}: stored channel has no connectors')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default=DEFAULT_URL)
    parser.add_argument('--user', default=DEFAULT_USER)
    parser.add_argument('--password', default=DEFAULT_PASS)
    parser.add_argument('--undeploy', action='store_true',
                        help='undeploy the channels instead of deploying them')
    parser.add_argument('--timeout', type=int, default=60,
                        help='seconds to wait for channels to reach STARTED')
    args = parser.parse_args()

    mirth = Mirth(args.url, args.user, args.password)
    try:
        logger.info('[deploy] Mirth Connect %s at %s', mirth.version(), args.url)
    except requests.RequestException as exc:
        logger.error('[deploy] Cannot reach Mirth at %s: %s', args.url, exc)
        return 1

    paths = sorted(glob.glob(os.path.join(CHANNEL_DIR, '*.xml')))
    if not paths:
        logger.error('[deploy] No channel XML found in %s', CHANNEL_DIR)
        return 1
    logger.info('[deploy] Found %d channel files', len(paths))

    channels: list[tuple[str, str, str]] = []
    for path in paths:
        xml = open(path, encoding='utf-8').read()
        root = ET.fromstring(xml)
        cid, name = root.findtext('id'), root.findtext('name')
        if not cid or not name:
            logger.error('[deploy] %s has no id or name — skipped', path)
            continue
        channels.append((cid, name, xml))

    if args.undeploy:
        for cid, name, _ in channels:
            mirth.undeploy(cid)
            logger.info('[deploy] Undeployed %s', name)
        return 0

    # Import every channel before deploying any of them. Note_Outbound's TCP
    # destination points at EHR_Mock's listener, so a partial import would
    # deploy a sender aimed at a receiver that does not exist yet.
    for cid, name, xml in channels:
        mirth.put_channel(xml, cid)
        _verify(mirth, cid, name)
        logger.info('[deploy] Imported %-16s %s', name, cid)

    mirth.enable([cid for cid, _, _ in channels])
    logger.info('[deploy] Enabled %d channels', len(channels))

    failed = []
    for cid, name, _ in channels:
        try:
            mirth.deploy(cid)
            logger.info('[deploy] Deploy requested for %s', name)
        except RuntimeError as exc:
            logger.error('[deploy] %s FAILED: %s', name, exc)
            failed.append(name)

    # Deploy is asynchronous and returns before connectors bind their ports.
    wanted = {name for _, name, _ in channels} - set(failed)
    deadline = time.time() + args.timeout
    statuses: dict[str, str] = {}
    while time.time() < deadline:
        statuses = mirth.statuses()
        if wanted and all(statuses.get(n) == 'STARTED' for n in wanted):
            break
        time.sleep(2)

    logger.info('[deploy] --- final channel states ---')
    for _, name, _ in channels:
        state = statuses.get(name, 'NOT DEPLOYED')
        level = logging.INFO if state == 'STARTED' else logging.ERROR
        logger.log(level, '[deploy]   %-16s %s', name, state)

    not_started = [n for n in wanted if statuses.get(n) != 'STARTED']
    if failed or not_started:
        logger.error('[deploy] %d channel(s) did not start', len(failed) + len(not_started))
        return 1
    logger.info('[deploy] All %d channels STARTED', len(channels))
    return 0


if __name__ == '__main__':
    sys.exit(main())
