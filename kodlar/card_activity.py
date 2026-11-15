"""One lightweight Tk timer for subtle feedback on cards that actually fired."""
from __future__ import annotations

import time
import tkinter as tk


def blend(first, second, amount):
    a = tuple(int(first[i:i+2], 16) for i in (1, 3, 5))
    b = tuple(int(second[i:i+2], 16) for i in (1, 3, 5))
    return '#' + ''.join(f'{round(x+(y-x)*amount):02x}' for x, y in zip(a, b))


class CardActivity:
    DURATION = .32

    def __init__(self, root):
        self.root = root
        self.cards = {}
        self.job = None

    def pulse(self, widgets):
        card, stripe = widgets['card'], widgets['stripe']
        if card in self.cards or not card.winfo_exists():
            return
        self.cards[card] = (stripe, time.monotonic(), card.cget('highlightbackground'), stripe.cget('bg'))
        if self.job is None:
            self.tick()

    def tick(self):
        self.job = None
        now = time.monotonic()
        for card, (stripe, started, border, color) in list(self.cards.items()):
            if not card.winfo_exists():
                del self.cards[card]
                continue
            phase = (now-started)/self.DURATION
            if phase >= 1:
                card.configure(highlightbackground=border)
                stripe.configure(bg=color)
                del self.cards[card]
                continue
            strength = min(1.0, phase/.18, (1-phase)/.82)
            card.configure(highlightbackground=blend(border, '#8bb8ee', .48*strength))
            stripe.configure(bg=blend(color, '#d2e7ff', .28*strength))
        if self.cards:
            self.job = self.root.after(33, self.tick)

    def clear(self):
        if self.job is not None:
            self.root.after_cancel(self.job)
            self.job = None
        for card, (stripe, _started, border, color) in self.cards.items():
            try:
                if card.winfo_exists():
                    card.configure(highlightbackground=border)
                    stripe.configure(bg=color)
            except tk.TclError:
                pass
        self.cards.clear()
