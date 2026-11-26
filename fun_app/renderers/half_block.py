"""Incremental ANSI encoding for text and half-block frames."""


class _Esc(dict):
    def __init__(self, prefix, suffix=b'm'):
        dict.__init__(self)
        self.prefix = prefix
        self.suffix = suffix

    def __missing__(self, c):
        if len(self) > 60000:      # bound memory
            self.clear()
        s = b'%s%d;%d;%d%s' % (self.prefix, c >> 16, (c >> 8) & 255, c & 255, self.suffix)
        self[c] = s
        return s


class _CharBytes(dict):
    def __missing__(self, ch):
        if len(self) > 16000:      # bound memory
            self.clear()
        b = ch.encode('utf-8')
        self[ch] = b
        return b


def _runs(idx, gap=4):
    runs = []
    s = p = idx[0]
    for x in idx[1:]:
        if x - p > gap:
            runs.append((s, p + 1))
            s = x
        p = x
    runs.append((s, p + 1))
    return runs


class Encoder:
    """Diffing ANSI encoder.  Returns bytes (or b'' when nothing changed)."""

    def __init__(self):
        self.fg = _Esc(b'\x1b[38;2;')
        self.bg = _Esc(b'\x1b[48;2;')
        self._fg_half = _Esc(b'\x1b[38;2;', b'm\xe2\x96\x80')
        self._fg_open = _Esc(b'\x1b[38;2;', b'')
        self._bg_sp = _Esc(b'\x1b[48;2;', b'm ')
        self._bg_half = _Esc(b'\x1b[48;2;', b'm\xe2\x96\x80')
        self._bg_chain = _Esc(b';48;2;', b'm\xe2\x96\x80')
        self._ch = _CharBytes()
        self.prev = None
        self.prev2 = None
        self._w = 0
        self._rows = 0
        self._mask = None
        self._row_home = ()

    def reset(self):
        self.prev = None
        self.prev2 = None
        self._mask = None

    def _ensure_geometry(self, W, rows):
        if self._w != W or self._rows != rows:
            self._w = W
            self._rows = rows
            self._row_home = tuple(b'\x1b[%d;1H' % (cy + 1) for cy in range(rows))
            return True
        return False

    def blocks(self, buf, W, rows, mask=0xFFFFFF):
        resized = self._ensure_geometry(W, rows)
        prev = None if (resized or self._mask != mask) else self.prev
        self._mask = mask
        prev_rows = [None] * rows if prev is None else prev
        FG_HALF = self._fg_half
        FG_OPEN = self._fg_open
        BG_SP = self._bg_sp
        BG_HALF = self._bg_half
        BG_CHAIN = self._bg_chain
        row_home = self._row_home
        out = [b'\x1b[?2026h']
        ap = out.append
        lf = lb = -1
        do_mask = mask != 0xFFFFFF
        a = 0
        for cy in range(rows):
            m = a + W
            e = m + W
            rtop = buf[a:m]
            rbot = buf[m:e]
            a = e
            if prev is None:
                if do_mask:
                    top = [c & mask for c in rtop]
                    bot = [c & mask for c in rbot]
                    prev_rows[cy] = (rtop, rbot, top, bot)
                else:
                    top, bot = rtop, rbot
                    prev_rows[cy] = (top, bot)
                runs = ((0, W),)
            else:
                if do_mask:
                    prtop, prbot, ptop, pbot = prev_rows[cy]
                    top_same = rtop == prtop
                    bot_same = rbot == prbot
                    if top_same and bot_same:
                        continue
                    top = ptop if top_same else [c & mask for c in rtop]
                    bot = pbot if bot_same else [c & mask for c in rbot]
                    if not top_same and top == ptop:
                        top_same = True
                    if not bot_same and bot == pbot:
                        bot_same = True
                    if top_same and bot_same:
                        prev_rows[cy] = (rtop, rbot, ptop, pbot)
                        continue
                    prev_rows[cy] = (rtop, rbot, top, bot)
                else:
                    ptop, pbot = prev_rows[cy]
                    top_same = rtop == ptop
                    bot_same = rbot == pbot
                    if top_same and bot_same:
                        continue
                    top, bot = rtop, rbot
                    prev_rows[cy] = (top, bot)
                if top_same:
                    idx = [x for x in range(W) if bot[x] != pbot[x]]
                elif bot_same:
                    idx = [x for x in range(W) if top[x] != ptop[x]]
                else:
                    idx = [x for x in range(W) if top[x] != ptop[x] or bot[x] != pbot[x]]
                if idx[-1] - idx[0] == len(idx) - 1:
                    runs = ((idx[0], idx[-1] + 1),)
                else:
                    runs = _runs(idx)
            row1 = cy + 1
            for x0, x1 in runs:
                ap(row_home[cy] if x0 == 0 else b'\x1b[%d;%dH' % (row1, x0 + 1))
                for x in range(x0, x1):
                    t = top[x]
                    b = bot[x]
                    if t == b:
                        if b != lb:
                            ap(BG_SP[b])
                            lb = b
                        else:
                            ap(b' ')
                    elif t != lf:
                        lf = t
                        if b != lb:
                            ap(FG_OPEN[t])
                            ap(BG_CHAIN[b])
                            lb = b
                        else:
                            ap(FG_HALF[t])
                    elif b != lb:
                        ap(BG_HALF[b])
                        lb = b
                    else:
                        ap(b'\xe2\x96\x80')
        self.prev = prev_rows
        if len(out) == 1:
            return b''
        ap(b'\x1b[?2026l')
        return b''.join(out)

    def text(self, chars, fgs, W, rows):
        resized = self._ensure_geometry(W, rows)
        prev = None if resized else self.prev2
        prev_rows = [None] * rows if prev is None else prev
        FG = self.fg
        CH = self._ch
        row_home = self._row_home
        out = [b'\x1b[?2026h', self.bg[0]]
        ap = out.append
        lf = -1
        a = 0
        for cy in range(rows):
            e = a + W
            ch = chars[a:e]
            fg = fgs[a:e]
            a = e
            if prev is None:
                prev_rows[cy] = (ch, fg)
                runs = ((0, W),)
            else:
                pc, pf = prev_rows[cy]
                ch_same = ch == pc
                fg_same = fg == pf
                if ch_same and fg_same:
                    continue
                prev_rows[cy] = (ch, fg)
                if ch_same:
                    idx = [x for x in range(W) if fg[x] != pf[x]]
                elif fg_same:
                    idx = [x for x in range(W) if ch[x] != pc[x]]
                else:
                    idx = [x for x in range(W) if ch[x] != pc[x] or fg[x] != pf[x]]
                if idx[-1] - idx[0] == len(idx) - 1:
                    runs = ((idx[0], idx[-1] + 1),)
                else:
                    runs = _runs(idx)
            row1 = cy + 1
            for x0, x1 in runs:
                ap(row_home[cy] if x0 == 0 else b'\x1b[%d;%dH' % (row1, x0 + 1))
                for x in range(x0, x1):
                    c = ch[x]
                    if c == ' ':
                        ap(b' ')
                    else:
                        f = fg[x]
                        if f != lf:
                            ap(FG[f])
                            lf = f
                        ap(CH[c])
        self.prev2 = prev_rows
        if len(out) <= 2:
            return b''
        ap(b'\x1b[?2026l')
        return b''.join(out)
