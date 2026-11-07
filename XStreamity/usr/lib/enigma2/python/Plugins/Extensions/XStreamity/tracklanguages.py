#!/usr/bin/python
# -*- coding: utf-8 -*-

"""
Language table shared by the XStreamity settings screen and the automatic
audio / subtitle track selection (trackselection.py).

Each entry: ISO 639-1 code -> (English name, other codes / names streams use)
"""

from __future__ import absolute_import

LANGS = {
    "ar": ("Arabic", ("ara", "arabic")),
    "bg": ("Bulgarian", ("bul", "bulgarian")),
    "bs": ("Bosnian", ("bos", "bosnian")),
    "ca": ("Catalan", ("cat", "catalan")),
    "cs": ("Czech", ("ces", "cze", "czech")),
    "cy": ("Welsh", ("cym", "wel", "welsh")),
    "da": ("Danish", ("dan", "danish")),
    "de": ("German", ("deu", "ger", "german", "deutsch")),
    "el": ("Greek", ("ell", "gre", "greek")),
    "en": ("English", ("eng", "english")),
    "es": ("Spanish", ("spa", "spanish", "espanol", "castellano")),
    "et": ("Estonian", ("est", "estonian")),
    "eu": ("Basque", ("eus", "baq", "basque")),
    "fa": ("Persian", ("fas", "per", "persian", "farsi")),
    "fi": ("Finnish", ("fin", "finnish")),
    "fr": ("French", ("fra", "fre", "french", "francais")),
    "ga": ("Irish", ("gle", "irish")),
    "gd": ("Gaelic", ("gla", "gaelic")),
    "gl": ("Galician", ("glg", "galician")),
    "he": ("Hebrew", ("heb", "hebrew")),
    "hi": ("Hindi", ("hin", "hindi")),
    "hr": ("Croatian", ("hrv", "scr", "croatian")),
    "hu": ("Hungarian", ("hun", "hungarian")),
    "id": ("Indonesian", ("ind", "indonesian")),
    "is": ("Icelandic", ("isl", "ice", "icelandic")),
    "it": ("Italian", ("ita", "italian", "italiano")),
    "ja": ("Japanese", ("jpn", "japanese")),
    "ko": ("Korean", ("kor", "korean")),
    "ku": ("Kurdish", ("kur", "kurdish")),
    "lt": ("Lithuanian", ("lit", "lithuanian")),
    "lv": ("Latvian", ("lav", "latvian")),
    "mk": ("Macedonian", ("mkd", "mac", "macedonian")),
    "ms": ("Malay", ("msa", "may", "malay")),
    "mt": ("Maltese", ("mlt", "maltese")),
    "nl": ("Dutch", ("nld", "dut", "dutch", "nederlands")),
    "no": ("Norwegian", ("nor", "nob", "nno", "norwegian")),
    "pl": ("Polish", ("pol", "polish", "polski")),
    "pt": ("Portuguese", ("por", "portuguese", "portugues")),
    "ro": ("Romanian", ("ron", "rum", "romanian")),
    "ru": ("Russian", ("rus", "russian")),
    "sk": ("Slovak", ("slk", "slo", "slovak")),
    "sl": ("Slovenian", ("slv", "slovenian")),
    "sq": ("Albanian", ("sqi", "alb", "albanian")),
    "sr": ("Serbian", ("srp", "scc", "serbian")),
    "sv": ("Swedish", ("swe", "swedish")),
    "th": ("Thai", ("tha", "thai")),
    "tr": ("Turkish", ("tur", "turkish")),
    "uk": ("Ukrainian", ("ukr", "ukrainian")),
    "ur": ("Urdu", ("urd", "urdu")),
    "vi": ("Vietnamese", ("vie", "vietnamese")),
    "zh": ("Chinese", ("zho", "chi", "chinese", "mandarin", "cantonese")),
}


def language_choices(translate=None):
    """Choices for a ConfigSelection: ("", None) followed by languages A-Z."""
    tr = translate or (lambda s: s)
    choices = [(code, tr(name)) for code, (name, _aliases) in LANGS.items()]
    choices.sort(key=lambda c: c[1])
    return [("", tr("None"))] + choices
