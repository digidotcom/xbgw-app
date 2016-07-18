# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright (c) 2016 Digi International Inc. All Rights Reserved.

from nose.tools import assert_raises, eq_
from xbgw.xbee.utils import CallbacksFull, TxStatusCallbacks

########################################################################
# Tests related to TxStatusCallbacks class.

def test_tx_status_callbacks_creation():
    """
    TxStatusCallbacks with no args should set max_id to 255,
    and should respect the max_id value you pass in otherwise.
    """
    uut = TxStatusCallbacks()
    eq_(uut.max_id, 255)
    uut = TxStatusCallbacks(max_id=20)
    eq_(uut.max_id, 20)

def test_txscb_add_get():
    """
    Check that after adding a callback, that callback can be retrieved using
    get_callback(<transmission id>)
    """
    uut = TxStatusCallbacks(max_id=10)
    cb = object()
    txid = uut.add_callback(cb)
    eq_(cb, uut.get_callback(txid))

def test_txscb_remove_callback():
    """
    Check that removing a callback works. (At a lower level, check that
    removing a callback causes a successive attempt to retrieve the callback to
    return None.)
    """
    uut = TxStatusCallbacks()
    cb = object()
    txid = uut.add_callback(cb)
    eq_(cb, uut.get_callback(txid))

    uut.remove_callback(txid)
    eq_(None, uut.get_callback(txid))

# Lower-level TxStatusCallback behavioral tests
def test_txscb_id_wraps():
    """
    When the max ID is reached, the transmission ID should wrap around to lower
    numbers.
    """
    uut = TxStatusCallbacks(5)
    for i in xrange(1, 6):
        print i
        txid = uut.add_callback(object())
        assert txid == i, "Callback #%d got ID %d" % (i, txid)
    # Remove callback for ID 2, to check the wrapping works.
    uut.remove_callback(2)
    next_id = uut.add_callback(object())
    assert next_id == 2

    # Remove callback for ID 1, to check that it wraps back around.
    uut.remove_callback(1)
    next_id = uut.add_callback(object())
    assert next_id == 1

def test_txscb_callbacks_full():
    """
    When the callback map is full, attempting to add a callback should
    result in CallbacksFull being raised.
    """
    uut = TxStatusCallbacks(5)
    for i in xrange(1, 6):
        uut.add_callback(object())

    with assert_raises(CallbacksFull):
        uut.add_callback(object())
