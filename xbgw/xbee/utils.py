# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

"""
Define utility functions and classes for XBee application support
"""

from collections import namedtuple
import string
import threading


def normalize_ieee_address(address):
    """
    Normalize the representation of the 64-bit address of a ZigBee device to
    the form of an address fit for an XBee node. The provided address value may
    either be an int, long, or hexadecimal string. This hexadecimal string may
    include optional separator characters for human readability.
    """
    if isinstance(address, basestring):
        hexonly = ''.join((c for c in address if c in string.hexdigits))
        # Check that there are at least one, but no more than 16 digits.
        if 0 < len(hexonly) <= 16:
            value = long(hexonly, 16)
        else:
            # Address is either too long or too short (empty).
            # Note: We may choose later to further validate this string or its
            # length. For example, we could check that its length is not below
            # some number, meaning that we limit the allowable number of
            # leading zeros to be added to the address.
            count = len(hexonly)
            if count > 16:
                raise ValueError("Address is too long (%d chars)" % count)
            else:  # No hex digits were found.
                raise ValueError("Address is too short (%d chars)" % count)
    elif isinstance(address, (int, long)):
        value = long(address)
    else:
        message = "Network address must be given as a string, int or long"
        raise TypeError(message)

    # Get a string of the form XX:XX:XX:XX:XX:XX:XX:XX
    mac = ':'.join((
        ''.join((string.hexdigits[0xF & (value >> (i * 8 + 4))].upper(),
                 string.hexdigits[0xF & (value >> (i * 8))].upper()))
        for i in xrange(7, -1, -1)
    ))

    # Return a string of the form [XX:XX:XX:XX:XX:XX:XX:XX]!
    return ''.join(('[', mac, ']!'))

# Field names for Address
_address_fields = 'address endpoint profile cluster optionsmask txid'


# pylint: disable=no-init,no-member,super-on-old-class,too-many-arguments
class Address(namedtuple('Address', _address_fields)):
    """
    namedtuple class providing simpler access to XBee socket address fields
    """

    def __new__(cls, address, endpoint, profile, cluster,
                optionsmask=0, txid=0):
        address = normalize_ieee_address(address)
        # Make optionsmask and txid optional arguments
        return super(Address, cls).__new__(
            cls, address, endpoint, profile, cluster,
            optionsmask=optionsmask, txid=txid)

    def __str__(self):
        tup = self.to_tuple()
        addr, numbers = tup[0], tup[1:]
        hexvals = ', '.join(hex(i) for i in numbers)
        return "('%s', %s)" % (addr, hexvals)

    def to_tuple(self):
        numbers = (self.endpoint, self.profile, self.cluster)
        if self.optionsmask or self.txid:
            # Add these only if either is non-zero
            numbers += (self.optionsmask, self.txid)

        return (self.address,) + numbers


class CallbacksFull(Exception):
    """
    Exception raised by TxStatusCallbacks.add_callback when all slots are full
    """
    pass


class TxStatusCallbacks(object):
    """
    Utility structure mapping 'transmission IDs' to their associated callbacks

    At its core, TxStatusCallbacks is a wrapper around a fixed-size list, where
    new items are added into the first available slot (or else an error is
    returned if no slots are available) and the slot ID is returned, and items
    can be looked up and removed by their slot ID.

    This data structure is used by the XBee socket managers
    (see XBeeEventManager and DDOEventManager) to generate transmissions IDs,
    track pending transmissions, and trigger responses upon receipt of
    TX status frames from the XBee.
    """

    def __init__(self, max_id=255):
        self._callbacks = [None] * (max_id + 1)
        self._baseindex = 1
        self.max_id = max_id
        self._maplock = threading.Lock()

    def _next_index(self):
        """
        Finds the next open slot in the callback list, or 0 if there are no
        available slots.
        """
        start = self._baseindex % (self.max_id + 1)
        try:
            # Let the callback list wrap around, but start at the base index,
            # and skip index 0.
            cblist = self._callbacks[start:] + self._callbacks[1:start]
            # The index call will raise ValueError if there are no None values.
            index = cblist.index(None) + start
            if index > len(cblist):
                index %= len(cblist)
            return index
        except ValueError:
            return 0

    def add_callback(self, listener):
        """
        Adds the given listener to a map from transmission_id to listener, and
        returns the transmission ID to use. Raises CallbacksFull if there are
        no available transmission IDs.
        """
        with self._maplock:
            txid = self._next_index()
            if not txid:
                # No available spaces.
                raise CallbacksFull
            self._callbacks[txid] = listener
            # Increment base index, wrapping around if necessary.
            self._baseindex += 1
            if self._baseindex > self.max_id:
                self._baseindex = 1
            return txid

    def remove_callback(self, txid):
        """
        Remove the callback associated with 'txid'.
        """
        if txid <= 0 or txid > self.max_id:
            # Callback number is outside the valid range.
            raise IndexError("Not a valid transmission ID: %d" % txid)
        with self._maplock:
            # Clear up the transmission ID by setting its callback to None.
            self._callbacks[txid] = None

    def get_callback(self, txid):
        if txid <= 0 or txid > self.max_id:
            raise IndexError("Not a valid transmission ID: %d" % txid)
        return self._callbacks[txid]
