"""Send a synthetic ADT message to the ADT_Inbound channel over MLLP.

The registration feed a real deployment would receive from a hospital's ADT
interface, reduced to something runnable on a laptop.

    python mirth/tools/send_adt.py
    python mirth/tools/send_adt.py --mrn MRN990011 --event A08 --family Alvarez

SYNTHETIC DATA ONLY. Every name, MRN and NPI produced here is invented. Never
point this at a system carrying real patient data.

MLLP framing, HL7 v2.5 Chapter 2: <VT> message <FS><CR>, i.e. 0x0B ... 0x1C 0x0D.
A bare TCP write without those bytes is the most common reason a v2 interface
appears to connect and then never delivers anything.
"""

from __future__ import annotations

import argparse
import datetime as dt
import logging
import random
import socket
import sys

logging.basicConfig(level=logging.INFO, format='%(levelname)-5s %(message)s')
logger = logging.getLogger('send_adt')

SB, EB, CR = b'\x0b', b'\x1c', b'\x0d'

# NPIs here are syntactically valid but deliberately fictional.
DEFAULT_NPI = '1234567893'


def build_adt(mrn: str, event: str, family: str, given: str, birth_date: str,
              sex: str, patient_class: str, npi: str, facility: str) -> str:
    now = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d%H%M%S')
    control_id = f'{event}{random.randint(100000, 999999)}'

    segments = [
        # MSH-11 'T' — this is test/training data, and saying so in the message
        # is the honest thing to do. A synthetic feed marked 'P' is how test
        # data ends up treated as production.
        f'MSH|^~\\&|REGISTRATION|{facility}|HISCRIBE|HISCRIBE_DEV|{now}||'
        f'ADT^{event}^ADT_{event}|{control_id}|T|2.5',
        f'EVN|{event}|{now}',
        # PID-3 carries the identifier list; ^^^assigning authority^MR marks it
        # as a medical record number (table 0203).
        f'PID|1||{mrn}^^^{facility}^MR||{family}^{given}^^^^^L||{birth_date}|{sex}',
    ]

    # Built by index rather than by counting pipes. PV1-19 (Visit Number) sits
    # eleven empty fields past PV1-7, and getting that count right by eye is how
    # a value silently lands in the wrong field.
    pv1 = [''] * 20
    pv1[0]  = 'PV1'
    pv1[1]  = '1'                                    # PV1-1  Set ID
    pv1[2]  = patient_class                          # PV1-2  Patient Class (0004)
    pv1[3]  = f'CLINIC^^^{facility}'                 # PV1-3  Assigned Location
    pv1[7]  = f'{npi}^SMITH^ALAN^^^^^^NPI'           # PV1-7  Attending Doctor
    pv1[19] = f'V{random.randint(100000, 999999)}'   # PV1-19 Visit Number
    segments.append('|'.join(pv1))

    return '\r'.join(segments) + '\r'


def send_mllp(host: str, port: int, message: str, timeout: float = 15.0) -> str:
    framed = SB + message.encode('utf-8') + EB + CR
    logger.info('[send_adt] Connecting to %s:%d', host, port)
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(framed)
        logger.info('[send_adt] Sent %d bytes, waiting for ACK', len(framed))
        buf = b''
        sock.settimeout(timeout)
        while EB not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
    return buf.strip(SB + EB + CR).decode('utf-8', errors='replace')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='localhost')
    parser.add_argument('--port', type=int, default=6661)
    parser.add_argument('--mrn', default='MRN123456')
    parser.add_argument('--event', default='A01', choices=['A01', 'A04', 'A08', 'A03'],
                        help='A03 is included so the filter path can be exercised')
    parser.add_argument('--family', default='DOE')
    parser.add_argument('--given', default='JANE')
    parser.add_argument('--birth-date', default='19850214')
    parser.add_argument('--sex', default='F')
    parser.add_argument('--patient-class', default='O')
    parser.add_argument('--npi', default=DEFAULT_NPI)
    parser.add_argument('--facility', default='MEMORIAL_SIM')
    args = parser.parse_args()

    message = build_adt(args.mrn, args.event, args.family, args.given,
                        args.birth_date, args.sex, args.patient_class,
                        args.npi, args.facility)
    print('--- sending ---')
    print(message.replace('\r', '\n').rstrip())

    try:
        ack = send_mllp(args.host, args.port, message)
    except (socket.timeout, OSError) as exc:
        logger.error('[send_adt] MLLP send failed: %s', exc)
        return 1

    print('--- ACK ---')
    print(ack.replace('\r', '\n').rstrip() or '(no ACK received)')

    for line in ack.replace('\r\n', '\r').replace('\n', '\r').split('\r'):
        if line.startswith('MSA|'):
            code = line.split('|')[1] if len(line.split('|')) > 1 else '?'
            if code != 'AA':
                logger.error('[send_adt] Receiver returned MSA-1=%s', code)
                return 1
            logger.info('[send_adt] Accepted (MSA-1=AA)')
            return 0

    logger.warning('[send_adt] Response carried no MSA segment')
    return 1


if __name__ == '__main__':
    sys.exit(main())
