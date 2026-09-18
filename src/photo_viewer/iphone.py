import ctypes
import gc
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from ctypes import HRESULT, POINTER, c_ulong, c_void_p
from dataclasses import dataclass
from datetime import datetime

import comtypes
import comtypes.client
from comtypes import COMMETHOD, GUID, IUnknown

from photo_viewer.i18n import tr

_api = comtypes.client.GetModule("PortableDeviceApi.dll")

APPLE_USB_VENDOR = "vid_05ac"
_ROOT_OBJECT = "DEVICE"
_STGM_READ = 0
_BATCH_SIZE = 256
_DATE_FORMAT = "%Y/%m/%d:%H:%M:%S.%f"
_LISTING_ATTEMPTS = 2
_LISTING_RETRY_DELAY_S = 1.0

_CLSID_VALUES = GUID("{0C15D503-D017-47CE-9016-7B3F978721CC}")
_CLSID_KEY_COLLECTION = GUID("{DE2D022D-2480-43BE-97F0-D1FA2CF98F4F}")


def _property_key(fmtid: str, pid: int):
    key = _api._tagpropertykey()
    key.fmtid = GUID(fmtid)
    key.pid = pid
    return key


_OBJECT_PROPERTIES = "{EF6B490D-5CD8-437A-AFFC-DA8B60EE4A3C}"
_NAME = _property_key(_OBJECT_PROPERTIES, 12)
_SIZE = _property_key(_OBJECT_PROPERTIES, 11)
_MODIFIED = _property_key(_OBJECT_PROPERTIES, 19)
_DEFAULT_RESOURCE = _property_key("{E81E79BE-34F0-41BF-B53F-F1A06AE87842}", 0)


class _ObjectIds(IUnknown):
    """IEnumPortableDeviceObjectIDs with a working `Next` signature (the type library's is broken)."""

    _iid_ = _api.IEnumPortableDeviceObjectIDs._iid_
    _methods_ = (
        COMMETHOD(
            [],
            HRESULT,
            "Next",
            (["in"], c_ulong, "count"),
            (["in"], POINTER(c_void_p), "ids"),
            (["out"], POINTER(c_ulong), "fetched"),
        ),
    )


class _DeviceManager(IUnknown):
    """IPortableDeviceManager with a working `GetDevices` signature."""

    _iid_ = _api.IPortableDeviceManager._iid_
    _methods_ = (
        COMMETHOD(
            [],
            HRESULT,
            "GetDevices",
            (["in"], POINTER(c_void_p), "ids"),
            (["in", "out"], POINTER(c_ulong), "count"),
        ),
        COMMETHOD([], HRESULT, "RefreshDeviceList"),
    )


class IPhoneNotFoundError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DeviceFile:
    object_id: str
    name: str
    size: int
    modified: float


@dataclass(frozen=True, slots=True)
class DeviceFolder:
    object_id: str
    name: str


@contextmanager
def com_apartment():
    """COM must be initialised per thread. Release every COM object before leaving the block."""
    comtypes.CoInitialize()
    try:
        yield
    finally:
        gc.collect()
        comtypes.CoUninitialize()


def _create(clsid, interface):
    return comtypes.client.CreateObject(clsid, interface=interface)


def _take_string(pointer: int) -> str:
    text = ctypes.wstring_at(pointer)
    ctypes.windll.ole32.CoTaskMemFree(c_void_p(pointer))
    return text


def _apple_device_ids() -> list[str]:
    manager = _create(_api.PortableDeviceManager, _api.IPortableDeviceManager).QueryInterface(_DeviceManager)
    manager.RefreshDeviceList()
    count = manager.GetDevices(None, 0)
    buffer = (c_void_p * count)()
    manager.GetDevices(buffer, count)
    ids = [_take_string(pointer) for pointer in buffer]
    return [device_id for device_id in ids if APPLE_USB_VENDOR in device_id.lower()]


class IPhone:
    def __init__(self, device_id: str) -> None:
        self._device = _create(_api.PortableDevice, _api.IPortableDevice)
        self._device.Open(device_id, _create(_CLSID_VALUES, _api.IPortableDeviceValues))
        content = self._device.Content()
        self._content = content
        self._properties = content.Properties()
        self._resources = content.Transfer()
        self._keys = _create(_CLSID_KEY_COLLECTION, _api.IPortableDeviceKeyCollection)
        for key in (_NAME, _SIZE, _MODIFIED):
            self._keys.Add(key)

    @classmethod
    def connect(cls) -> "IPhone":
        device_ids = _apple_device_ids()
        if not device_ids:
            raise IPhoneNotFoundError(tr("import.not_found"))
        return cls(device_ids[0])

    def close(self) -> None:
        with suppress(comtypes.COMError):
            self._device.Close()

    def folders(self) -> list[DeviceFolder]:
        return [
            DeviceFolder(folder, self._name(folder))
            for storage in self._children(_ROOT_OBJECT)
            for folder in self._children(storage)
        ]

    def object_ids(self, folder: DeviceFolder) -> list[str]:
        """Cheap listing of a folder's contents; properties are fetched separately by `describe`."""
        for _ in range(_LISTING_ATTEMPTS - 1):
            try:
                return self._children(folder.object_id)
            except comtypes.COMError:
                time.sleep(_LISTING_RETRY_DELAY_S)
        return self._children(folder.object_id)

    def describe(self, object_id: str) -> DeviceFile:
        values = self._properties.GetValues(object_id, self._keys)
        modified = datetime.strptime(values.GetStringValue(_MODIFIED), _DATE_FORMAT)
        return DeviceFile(
            object_id=object_id,
            name=values.GetStringValue(_NAME),
            size=values.GetUnsignedLargeIntegerValue(_SIZE),
            modified=modified.timestamp(),
        )

    def read(self, file: DeviceFile) -> Iterator[bytes]:
        chunk_size, stream = self._resources.GetStream(file.object_id, _DEFAULT_RESOURCE, _STGM_READ, 0)
        try:
            while True:
                chunk, count = stream.RemoteRead(chunk_size)
                if not count:
                    return
                yield bytes(chunk[:count])
        finally:
            del stream  # release the device stream right away, also when the reader gives up midway

    def _children(self, parent_id: str) -> list[str]:
        enumerator = self._content.EnumObjects(0, parent_id, None).QueryInterface(_ObjectIds)
        ids: list[str] = []
        while True:
            buffer = (c_void_p * _BATCH_SIZE)()
            fetched = enumerator.Next(_BATCH_SIZE, buffer)
            ids.extend(_take_string(pointer) for pointer in buffer[:fetched])
            if fetched < _BATCH_SIZE:
                return ids

    def _name(self, object_id: str) -> str:
        return self._properties.GetValues(object_id, self._keys).GetStringValue(_NAME)
