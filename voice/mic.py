"""Windows desktop glue for dictation, with ctypes only (no packages).

The hold-to-talk key, the microphone (MCI, part of Windows since forever)
and typing the transcription into the window that had the focus.
"""
import ctypes
import re
import sys
import time

# Keys that make a good hold-to-talk button: nobody types with them.
KEYS = {
    "pause": 0x13, "capslock": 0x14, "insert": 0x2D, "apps": 0x5D, "menu": 0x5D,
    "scrolllock": 0x91, "rctrl": 0xA3, "rightctrl": 0xA3, "ralt": 0xA5, "rightalt": 0xA5,
}
VK_RETURN = 0x0D
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOD_NOREPEAT = 0x4000
PM_REMOVE = 0x0001
HOTKEY_ID = 0x7A1C
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002


class MicError(RuntimeError):
    pass


def vk_code(name):
    """Virtual-key code of a key name: F1..F24, Pause, ScrollLock, RightCtrl... or 0x7B."""
    key = re.sub(r"[\s_-]", "", str(name)).lower()
    if re.fullmatch(r"f([1-9]|1\d|2[0-4])", key):
        return 0x6F + int(key[1:])
    if key in KEYS:
        return KEYS[key]
    if re.fullmatch(r"0x[0-9a-f]{1,2}", key):
        return int(key, 16)
    raise ValueError(f"Tecla desconocida: {name!r} (use F1–F24, Pause, ScrollLock, RightCtrl, RightAlt...)")


def utf16_units(text):
    """What SendInput types, one UTF-16 unit per key: accents, ñ and emoji included."""
    data = text.encode("utf-16-le")
    return [int.from_bytes(data[i:i + 2], "little") for i in range(0, len(data), 2)]


# Win32 structures with fixed-size types, so their layout (and size) is the
# same on any 64-bit Python; wintypes is only needed on Windows itself.
ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_uint16), ("wScan", ctypes.c_uint16), ("dwFlags", ctypes.c_uint32),
                ("time", ctypes.c_uint32), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_int32), ("dy", ctypes.c_int32), ("mouseData", ctypes.c_uint32),
                ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_uint32), ("wParamL", ctypes.c_uint16), ("wParamH", ctypes.c_uint16)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.c_uint32), ("u", _INPUTUNION)]


def key_events(text, enter=False):
    """INPUT records that type `text` (and press Enter)."""
    events = []
    for unit in utf16_units(text):
        for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
            events.append(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=0, wScan=unit, dwFlags=flags)))
    if enter:
        for flags in (0, KEYEVENTF_KEYUP):
            events.append(INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(wVk=VK_RETURN, wScan=0x1C, dwFlags=flags)))
    return events


class Recorder:
    """The default microphone through MCI: record, then save a 16 kHz mono WAV."""

    ALIAS = "talktome_mic"

    def __init__(self):
        self.winmm = ctypes.WinDLL("winmm")
        self.winmm.mciSendStringW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
        self.winmm.mciSendStringW.restype = ctypes.c_uint32
        self.winmm.mciGetErrorStringW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_uint]

    def _send(self, command):
        err = self.winmm.mciSendStringW(command, None, 0, None)
        if err:
            text = ctypes.create_unicode_buffer(256)
            self.winmm.mciGetErrorStringW(err, text, 256)
            raise MicError(f"micrófono ({command.split()[0]}): {text.value or err}")

    def _close(self):
        try:
            self._send(f"close {self.ALIAS}")
        except MicError:
            pass

    def start(self):
        self._close()  # a previous run that died mid-recording
        self._send(f"open new type waveaudio alias {self.ALIAS}")
        try:
            self._send(f"set {self.ALIAS} bitspersample 16 samplespersec 16000 channels 1 "
                       "bytespersec 32000 alignment 2")
        except MicError:
            pass  # the device's own format also works, only bigger
        self._send(f"record {self.ALIAS}")

    def stop(self, path):
        """Stop recording and return the WAV bytes (also kept at `path`)."""
        try:
            self._send(f"stop {self.ALIAS}")
            path.parent.mkdir(parents=True, exist_ok=True)
            self._send(f'save {self.ALIAS} "{path}"')
        finally:
            self._close()
        return path.read_bytes()

    def cancel(self):
        self._close()


class Desk:
    """The Windows desktop: the hold-to-talk key, the focused window and the keyboard."""

    def __init__(self, key):
        from ctypes import wintypes

        self.vk = vk_code(key)
        self.msg = wintypes.MSG()
        u = self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        u.GetForegroundWindow.restype = wintypes.HWND
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
        u.SendInput.restype = ctypes.c_uint
        u.GetAsyncKeyState.argtypes = [ctypes.c_int]
        u.GetAsyncKeyState.restype = ctypes.c_short
        u.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint,
                                   ctypes.c_uint]
        u.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        k = self.kernel32 = ctypes.WinDLL("kernel32")
        k.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        k.GlobalAlloc.restype = ctypes.c_void_p
        k.GlobalLock.argtypes = [ctypes.c_void_p]
        k.GlobalLock.restype = ctypes.c_void_p
        k.GlobalUnlock.argtypes = [ctypes.c_void_p]
        # As a hotkey the key never reaches the terminal, where it would type
        # an escape sequence into the prompt. Taken by another app: we still
        # see it, it just also goes to the window.
        self.exclusive = bool(u.RegisterHotKey(None, HOTKEY_ID, MOD_NOREPEAT, self.vk))

    def key_down(self):
        # Hotkey messages pile up in this thread's queue; nobody needs them.
        while self.user32.PeekMessageW(ctypes.byref(self.msg), None, 0, 0, PM_REMOVE):
            pass
        return bool(self.user32.GetAsyncKeyState(self.vk) & 0x8000)

    def foreground(self):
        return self.user32.GetForegroundWindow()

    def type_text(self, text, window, enter=True):
        """Type `text` into `window` and press Enter. False if that window is no longer in front."""
        if window and self.foreground() != window:
            self.user32.SetForegroundWindow(window)
            time.sleep(0.05)
            if self.foreground() != window:
                return False
        self._send(key_events(text))
        if enter:
            # Apart from the text: a terminal that gets both in one burst
            # may take the Enter as part of a paste.
            time.sleep(0.15)
            self._send(key_events("", enter=True))
        return True

    def _send(self, events):
        if not events:
            return
        array = (INPUT * len(events))(*events)
        if self.user32.SendInput(len(events), array, ctypes.sizeof(INPUT)) != len(events):
            # Windows blocks typing into a program with more privileges.
            raise MicError("Windows no dejó escribir en esa ventana (¿terminal como administrador? "
                           "Entonces ejecute también 'escucha' como administrador).")

    def copy(self, text):
        """Leave `text` on the clipboard."""
        data = ctypes.create_unicode_buffer(text)
        size = ctypes.sizeof(data)
        handle = self.kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        ctypes.memmove(self.kernel32.GlobalLock(handle), data, size)
        self.kernel32.GlobalUnlock(handle)
        if self.user32.OpenClipboard(None):
            try:
                self.user32.EmptyClipboard()
                self.user32.SetClipboardData(CF_UNICODETEXT, handle)
            finally:
                self.user32.CloseClipboard()

    def beep(self, kind):
        import winsound

        if kind == "start":
            winsound.Beep(1200, 40)
        else:
            winsound.Beep(330, 150)

    def recorder(self):
        return Recorder()

    def close(self):
        self.user32.UnregisterHotKey(None, HOTKEY_ID)


def available():
    return sys.platform == "win32"
