#!/usr/bin/env python
"""
touchosc2midi -- a TouchOSC to Midi Bridge.

(c) 2015 velolala <fiets@einstueckheilewelt.de>

Usage:
    touchosc2midi --help
    touchosc2midi list (backends | ports) [-v]
    touchosc2midi [(--midi-in <in> --midi-out <out>)] [--ip <oscserveraddress>] [-v]

Options:
    -h, --help                          Show this screen.
    --midi-in=<in>                      Full name or ID of midi input port.
    --midi-out=<out>                    Full name of or ID midi output port.
    --ip=<oscserveraddress>             Network address for OSC server (default: guess).
    -v, --verbose                       Verbose output.
"""
from __init__ import __version__
from docopt import docopt
import socket
import mido
import liblo
import logging
import time
from configuration import list_backends, list_ports, configure_ioports, get_mido_backend

from netaddr import IPNetwork

log = logging.getLogger(__name__)

PORT = 12345

def main_ip():
    """
    '192.0.2.0' is defined TEST-NET in RFC 5737,
    so there *shouldn't* be custom routing for this.

    :return: the IP of the default route's interface.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.connect(("192.0.2.0", 0))
    ip = sock.getsockname()[0]
    log.debug("Assuming {} for main route's IP.".format(ip))
    sock.close()
    return ip

def message_from_oscmidipayload(bites):
    """Convert the last 4 OSC-midi bytes into a mido message.
    """
    bites = bites[0][::-1][0:4]
    msg = mido.parse(bites)
    log.debug("Midi message to send is {}".format(msg))
    return msg


def message_to_oscmidipayload(message):
    """OSC 1.0 specs: 'Bytes from MSB to LSB are: port id, status byte, data1, data2'
    However, touchOSC seems to be: port id, data2, data1, status byte
    """
    # FIXME: port-id is 0?
    bites = [0] + message.bytes()
    assert len(bites) == 4
    return (bites[0], bites[3], bites[2], bites[1])


def create_callback_on_osc(sink):
    def callback(path, args, types, src):
        log.debug("OSC-Midi recieved from: {}:{} UDP: {} URL: {}".format(
            src.get_hostname(),
            src.get_port(),
            src.get_protocol() == liblo.UDP,
            src.get_url()))
        assert path == '/midi'
        assert types == 'm'
        log.debug("received /midi,m with args {}".format(args))
        sink.send(message_from_oscmidipayload(args))
    return callback


def create_callback_on_midi(target):
    def callback(message):
        if message.type == "clock":
            return
        log.debug("received: {}".format(message))
        b = message.bytes()
        osc = liblo.Message('/midi/{0}/{1}'.format(8, b[1]))
        osc.add(('f', (float(b[2]) / 128.0)))
        log.debug("Sending OSC-Midi {} to: {}:{} UDP: {} URL: {}".format(
            osc,
            target.get_hostname(),
            target.get_port(),
            target.get_protocol() == liblo.UDP,
            target.get_url()))
        liblo.send(target, osc)
    return callback


def main():
    options = docopt(__doc__, version=__version__)
    logging.basicConfig(level=logging.DEBUG if options.get('--verbose') else logging.INFO,
                        format="%(message)s")
    log.debug("Options from cmdline are {}".format(options))
    backend = get_mido_backend()
    if options.get('list'):
        if options.get('backends'):
            list_backends()
        elif options.get('ports'):
            list_ports(backend)
    else:
        try:
            midi_in, midi_out = configure_ioports(backend,
                                                  virtual=not (options.get('--midi-in') or
                                                               options.get('--midi-out')),
                                                  mido_in=options.get('--midi-in'),
                                                  mido_out=options.get('--midi-out'))

            ip = options.get('--ip')
            target_address = options.get('--ip')
            if not target_address:
                ip_network = IPNetwork(main_ip() + "/16")
                target_address = str(ip_network.broadcast)

            log.debug("Listening on {}:{}.".format(target_address, PORT))
            server = liblo.ServerThread(PORT)
            server.add_method('/midi', 'm', create_callback_on_osc(midi_out))

            target = liblo.Address(target_address, PORT + 1, liblo.UDP)
            log.info("Will send to {}.".format(target.get_url()))

            midi_in.callback = create_callback_on_midi(target)

            log.info("Listening for midi at {}.".format(midi_in))
            server.start()
            while True:
                time.sleep(.0001)
        except KeyboardInterrupt:
            server.stop()
            server.free()
            midi_in.close()
            log.info("closed all ports")

if __name__ == '__main__':
    main()
