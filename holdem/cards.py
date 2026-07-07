"""Cards and deck."""

from itertools import product

SUITS = "shdc"
SUIT_SYMBOLS = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
RED_SUITS = {"h", "d"}

RANK_CHARS = "23456789TJQKA"
RANK_VALUES = {ch: i + 2 for i, ch in enumerate(RANK_CHARS)}
VALUE_CHARS = {v: ch for ch, v in RANK_VALUES.items()}
# Display "T" as "10" for humans.
VALUE_LABELS = {v: ("10" if ch == "T" else ch) for v, ch in VALUE_CHARS.items()}

VALUE_NAMES = {
    2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven",
    8: "Eight", 9: "Nine", 10: "Ten", 11: "Jack", 12: "Queen",
    13: "King", 14: "Ace",
}


def plural(value):
    name = VALUE_NAMES[value]
    return name + ("es" if value == 6 else "s")


class Card:
    __slots__ = ("value", "suit")

    def __init__(self, value, suit):
        self.value = value
        self.suit = suit

    def __str__(self):
        return VALUE_LABELS[self.value] + SUIT_SYMBOLS[self.suit]

    def __repr__(self):
        return "Card(%r, %r)" % (self.value, self.suit)

    def __eq__(self, other):
        return isinstance(other, Card) and (self.value, self.suit) == (other.value, other.suit)

    def __hash__(self):
        return hash((self.value, self.suit))


class Deck:
    def __init__(self, rng):
        self.cards = [Card(v, s) for v, s in product(RANK_VALUES.values(), SUITS)]
        rng.shuffle(self.cards)

    def draw(self, n=1):
        drawn = self.cards[:n]
        del self.cards[:n]
        return drawn
