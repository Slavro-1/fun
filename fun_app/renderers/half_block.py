"""Incremental ANSI encoding for text and half-block frames."""



class _Esc(dict):
    def __init__(self, code):
        dict.__init__(self)
        self.code = code

    def __missing__(self, c):
        if len(self) > 60000:      # bound memory
            self.clear()
        s = '\x1b[%s;2;%d;%d;%dm' % (self.code, c >> 16, (c >> 8) & 255, c & 255)
        self[c] = s
        return s


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
        self.fg = _Esc('38')
        self.bg = _Esc('48')
        self.prev = None
        self.prev2 = None

    def reset(self):
        self.prev = None
        self.prev2 = None

    def blocks(self, buf, W, rows, mask=0xFFFFFF):
        if mask != 0xFFFFFF:
            buf = [c & mask for c in buf]
        prev = self.prev
        FG = self.fg
        BG = self.bg
        out = []
        ap = out.append
        lf = lb = -1
        for cy in range(rows):
            a = 2 * cy * W
            m = a + W
            e = m + W
            top = buf[a:m]
            bot = buf[m:e]
            if prev is None:
                runs = ((0, W),)
            else:
                ptop = prev[a:m]
                pbot = prev[m:e]
                if top == ptop and bot == pbot:
                    continue
                idx = [x for x in range(W) if top[x] != ptop[x] or bot[x] != pbot[x]]
                runs = _runs(idx)
            for x0, x1 in runs:
                ap('\x1b[%d;%dH' % (cy + 1, x0 + 1))
                for x in range(x0, x1):
                    t = top[x]
                    b = bot[x]
                    if t == b:
                        if b != lb:
                            ap(BG[b])
                            lb = b
                        ap(' ')
                    else:
                        if t != lf:
                            ap(FG[t])
                            lf = t
                        if b != lb:
                            ap(BG[b])
                            lb = b
                        ap('▀')
        self.prev = buf[:]
        if not out:
            return b''
        return ('\x1b[?2026h' + ''.join(out) + '\x1b[?2026l').encode('utf-8')

    def text(self, chars, fgs, W, rows):
        prev = self.prev
        pch, pfg = self.prev2 if prev is not None else (None, None)
        FG = self.fg
        BG = self.bg
        out = []
        ap = out.append
        ap(BG[0])
        lf = -1
        for cy in range(rows):
            a = cy * W
            e = a + W
            ch = chars[a:e]
            fg = fgs[a:e]
            if prev is None:
                runs = ((0, W),)
            else:
                pc = pch[a:e]
                pf = pfg[a:e]
                if ch == pc and fg == pf:
                    continue
                idx = [x for x in range(W) if ch[x] != pc[x] or fg[x] != pf[x]]
                runs = _runs(idx)
            for x0, x1 in runs:
                ap('\x1b[%d;%dH' % (cy + 1, x0 + 1))
                for x in range(x0, x1):
                    c = ch[x]
                    if c == ' ':
                        ap(' ')
                    else:
                        f = fg[x]
                        if f != lf:
                            ap(FG[f])
                            lf = f
                        ap(c)
        self.prev = True
        self.prev2 = (chars[:], fgs[:])
        if len(out) <= 1:
            return b''
        return ('\x1b[?2026h' + ''.join(out) + '\x1b[?2026l').encode('utf-8')
