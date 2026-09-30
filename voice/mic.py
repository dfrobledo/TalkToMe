"""Windows desktop glue for dictation, with ctypes only (no packages).

The hold-to-talk key (a low-level keyboard hook: exact press and release,
and the key never reaches the window), the microphone (waveIn, streaming
100 ms chunks as they are recorded) and typing the transcription into the
window that had the focus.
"""
import collections
import ctypes
import re
import sys
import threading
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
WH_KEYBOARD_LL = 13
WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP, WM_QUIT = 0x100, 0x101, 0x104, 0x105, 0x12
WAVE_MAPPER = 0xFFFFFFFF
WHDR_DONE = 0x1
RATE = 16000
CHUNK = RATE * 2 // 10  # 100 ms of 16-bit mono
BUFFERS = 10


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


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", ctypes.c_uint32), ("scanCode", ctypes.c_uint32), ("flags", ctypes.c_uint32),
                ("time", ctypes.c_uint32), ("dwExtraInfo", ULONG_PTR)]


class WAVEFORMATEX(ctypes.Structure):
    _pack_ = 1  # packed in mmreg.h
    _fields_ = [("wFormatTag", ctypes.c_uint16), ("nChannels", ctypes.c_uint16), ("nSamplesPerSec", ctypes.c_uint32),
                ("nAvgBytesPerSec", ctypes.c_uint32), ("nBlockAlign", ctypes.c_uint16),
                ("wBitsPerSample", ctypes.c_uint16), ("cbSize", ctypes.c_uint16)]


class WAVEHDR(ctypes.Structure):
    _fields_ = [("lpData", ctypes.c_void_p), ("dwBufferLength", ctypes.c_uint32), ("dwBytesRecorded", ctypes.c_uint32),
                ("dwUser", ULONG_PTR), ("dwFlags", ctypes.c_uint32), ("dwLoops", ctypes.c_uint32),
                ("lpNext", ctypes.c_void_p), ("reserved", ULONG_PTR)]


LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t


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
    """The default microphone through waveIn: 16 kHz mono, handed over in 100 ms chunks.

    `start(on_chunk)` calls on_chunk(pcm) from a background thread as audio
    arrives; `stop(path)` returns the whole recording as WAV bytes.
    """

    def __init__(self):
        w = self.winmm = ctypes.WinDLL("winmm")
        w.waveInOpen.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint, ctypes.POINTER(WAVEFORMATEX),
                                 ULONG_PTR, ULONG_PTR, ctypes.c_uint32]
        for name in ("waveInPrepareHeader", "waveInUnprepareHeader", "waveInAddBuffer"):
            getattr(w, name).argtypes = [ctypes.c_void_p, ctypes.POINTER(WAVEHDR), ctypes.c_uint]
        for name in ("waveInStart", "waveInStop", "waveInReset", "waveInClose"):
            getattr(w, name).argtypes = [ctypes.c_void_p]
        w.waveInGetErrorTextW.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_uint]
        self.handle = None

    def _check(self, err, what):
        if err:
            text = ctypes.create_unicode_buffer(256)
            self.winmm.waveInGetErrorTextW(err, text, 256)
            raise MicError(f"micrófono ({what}): {text.value or err}")

    def _queue(self, header):
        size = ctypes.sizeof(WAVEHDR)
        header.dwFlags, header.dwBytesRecorded = 0, 0
        self._check(self.winmm.waveInPrepareHeader(self.handle, ctypes.byref(header), size), "preparar")
        self._check(self.winmm.waveInAddBuffer(self.handle, ctypes.byref(header), size), "encolar")
        self.queue.append(header)

    def start(self, on_chunk=None):
        fmt = WAVEFORMATEX(wFormatTag=1, nChannels=1, nSamplesPerSec=RATE, nAvgBytesPerSec=RATE * 2,
                           nBlockAlign=2, wBitsPerSample=16, cbSize=0)
        handle = ctypes.c_void_p()
        self._check(self.winmm.waveInOpen(ctypes.byref(handle), WAVE_MAPPER, ctypes.byref(fmt), 0, 0, 0), "abrir")
        self.handle = handle
        self.on_chunk, self.chunks, self.queue = on_chunk, [], collections.deque()
        self.memory = [ctypes.create_string_buffer(CHUNK) for _ in range(BUFFERS)]
        self.headers = [WAVEHDR(lpData=ctypes.cast(buf, ctypes.c_void_p), dwBufferLength=CHUNK) for buf in self.memory]
        try:
            for header in self.headers:
                self._queue(header)
            self._check(self.winmm.waveInStart(self.handle), "grabar")
        except MicError:
            self._close()
            raise
        self.running = True
        self.pump = threading.Thread(target=self._pump, daemon=True)
        self.pump.start()

    def _collect(self):
        while self.queue and self.queue[0].dwFlags & WHDR_DONE:
            header = self.queue.popleft()
            data = ctypes.string_at(header.lpData, header.dwBytesRecorded)
            self.winmm.waveInUnprepareHeader(self.handle, ctypes.byref(header), ctypes.sizeof(WAVEHDR))
            if data:
                self.chunks.append(data)
                if self.on_chunk:
                    self.on_chunk(data)
            if self.running:
                self._queue(header)

    def _pump(self):
        while self.running:
            try:
                self._collect()
            except MicError:
                return
            time.sleep(0.01)

    def _close(self):
        if self.handle:
            self.winmm.waveInReset(self.handle)
            for header in self.headers:
                self.winmm.waveInUnprepareHeader(self.handle, ctypes.byref(header), ctypes.sizeof(WAVEHDR))
            self.winmm.waveInClose(self.handle)
            self.handle = None

    def stop(self, path=None):
        """Stop recording; the WAV bytes of everything recorded (also kept at `path`)."""
        from .stt import wav_bytes

        self.running = False
        self.pump.join()
        self.winmm.waveInStop(self.handle)  # the buffer being filled comes back done
        self.winmm.waveInReset(self.handle)
        self._collect()
        self._close()
        data = wav_bytes(b"".join(self.chunks), RATE)
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return data

    def cancel(self):
        self.running = False
        if getattr(self, "pump", None):
            self.pump.join()
        self._close()


class KeyWatcher(threading.Thread):
    """A low-level keyboard hook on one key: exact press and release, swallowed.

    Windows calls it for every key on the system, so it only flips a flag.
    """

    def __init__(self, vk):
        super().__init__(daemon=True)
        self.vk, self.down, self.ok = vk, False, False
        self.presses = 0
        self.ready = threading.Event()

    def run(self):
        from ctypes import wintypes

        u, k = ctypes.WinDLL("user32"), ctypes.WinDLL("kernel32")
        proc_type = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, WPARAM, LPARAM)
        u.SetWindowsHookExW.argtypes = [ctypes.c_int, proc_type, ctypes.c_void_p, ctypes.c_uint32]
        u.SetWindowsHookExW.restype = ctypes.c_void_p
        u.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, WPARAM, LPARAM]
        u.CallNextHookEx.restype = LRESULT
        u.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        u.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
        k.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
        k.GetModuleHandleW.restype = ctypes.c_void_p

        def on_key(code, wparam, lparam):
            if code == 0:
                info = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if info.vkCode == self.vk:
                    pressed = wparam in (WM_KEYDOWN, WM_SYSKEYDOWN)
                    if pressed and not self.down:
                        self.presses += 1
                    self.down = pressed
                    return 1  # swallowed: it never types into the terminal
            return u.CallNextHookEx(None, code, wparam, lparam)

        self._proc = proc_type(on_key)  # kept alive for as long as the hook
        self.thread_id = k.GetCurrentThreadId()
        hook = u.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, k.GetModuleHandleW(None), 0)
        self.ok = bool(hook)
        self.ready.set()
        if not hook:
            return
        msg = wintypes.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass  # the hook runs inside this loop
        u.UnhookWindowsHookEx(hook)

    def stop(self):
        if self.ok:
            ctypes.WinDLL("user32").PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)


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
        self.watcher = KeyWatcher(self.vk)
        self.watcher.start()
        self.watcher.ready.wait(2)
        self.hotkey = False
        if self.watcher.ok:
            self.exclusive = True
        else:
            # No hook: fall back to a hotkey, so at least the key does not
            # type an escape sequence into the prompt, and poll its state.
            self.hotkey = self.exclusive = bool(u.RegisterHotKey(None, HOTKEY_ID, MOD_NOREPEAT, self.vk))
        self.seen = 0

    def key_down(self):
        if self.watcher.ok:
            # A press shorter than one poll still counts: `presses` moved.
            tapped, self.seen = self.watcher.presses != self.seen, self.watcher.presses
            return self.watcher.down or tapped
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
        elif kind == "short":
            winsound.Beep(660, 60)
        else:
            winsound.Beep(330, 150)

    def recorder(self):
        return Recorder()

    def close(self):
        self.watcher.stop()
        if self.hotkey:
            self.user32.UnregisterHotKey(None, HOTKEY_ID)


def available():
    return sys.platform == "win32"
