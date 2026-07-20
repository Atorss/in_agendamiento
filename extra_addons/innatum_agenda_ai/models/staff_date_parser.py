# -*- coding: utf-8 -*-
"""Parser determinista de fechas escritas por el staff (español, Ecuador).

SIN LLM: regex + tablas. Entiende día+hora en formatos concretos y
devuelve un datetime UTC naive comparable con los huecos de
`_slots_libres`. Lo que no calza con los patrones → None (el agente cae
a las listas). La validación de pasado/ventana/hueco-libre es del
llamador. Spec: docs/superpowers/specs/
2026-07-10-staff-propone-dias-y-fecha-escrita-design.md
"""
import re
import unicodedata
from datetime import datetime, timedelta

# Ecuador continental: UTC-5 fijo, sin DST (mismo criterio que _fmt_dt_ec).
EC_OFFSET = timedelta(hours=5)

_DOW = {'lunes': 0, 'martes': 1, 'miercoles': 2, 'jueves': 3,
        'viernes': 4, 'sabado': 5, 'domingo': 6}

_RE_FECHA_NUM = re.compile(r'\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b')
_RE_PASADO = re.compile(r'\bpasado\s+manana\b')
_RE_MANANA = re.compile(r'\bmanana\b')
_RE_HOY = re.compile(r'\bhoy\b')
_RE_DOW = re.compile(r'\b(' + '|'.join(_DOW) + r')\b')
_RE_HORA = re.compile(r'\b(\d{1,2})(?:[:h](\d{2}))?\s*(am|pm)?\b')


def _normalizar(text):
    """minúsculas + sin tildes (mañana→manana, miércoles→miercoles)."""
    text = unicodedata.normalize('NFKD', (text or '').strip().lower())
    return ''.join(ch for ch in text if not unicodedata.combining(ch))


def _extraer_hora(text):
    """(hour, minute) o None. Exige minutos (15:00 / 09h30) o am/pm
    (3pm); un número suelto ("15") es ambiguo y se rechaza."""
    for m in _RE_HORA.finditer(text):
        hh, mm, ampm = int(m.group(1)), m.group(2), m.group(3)
        if mm is None and not ampm:
            continue
        minute = int(mm or 0)
        if minute > 59:
            continue
        if ampm:
            if not 1 <= hh <= 12:
                continue
            hh = hh % 12 + (12 if ampm == 'pm' else 0)
        elif hh > 23:
            continue
        return hh, minute
    return None


def parse_dia_suelto(text, ahora_utc):
    """Parsea un DÍA sin hora: 'mañana', 'el viernes', '15/07', 'hoy'.

    Es la variante para PACIENTES: en el funnel el paciente elige el día y
    recién después el horario (la hora la dan los botones), así que exigir
    hora —como hace `parse_fecha_escrita` para el staff— perdía respuestas
    perfectamente claras. Devuelve un `date` local o None.
    """
    text = _normalizar(text)
    if not text:
        return None
    hoy_local = (ahora_utc - EC_OFFSET).date()

    m = _RE_FECHA_NUM.search(text)
    if m:
        dd, mes, yy = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (1 <= dd <= 31 and 1 <= mes <= 12):
            return None
        year = int(yy) + (2000 if yy and len(yy) == 2 else 0) if yy \
            else hoy_local.year
        try:
            dia = hoy_local.replace(year=year, month=mes, day=dd)
        except ValueError:
            return None
        if not yy and dia < hoy_local:
            dia = dia.replace(year=year + 1)
        return dia
    if _RE_PASADO.search(text):
        return hoy_local + timedelta(days=2)
    if _RE_MANANA.search(text):
        return hoy_local + timedelta(days=1)
    if _RE_HOY.search(text):
        return hoy_local
    mdow = _RE_DOW.search(text)
    if mdow:
        # "el viernes" siendo viernes = el viernes que viene (hoy ya se
        # ofrece por defecto y pedirlo por nombre suele significar el próximo).
        delta = (_DOW[mdow.group(1)] - hoy_local.weekday()) % 7 or 7
        return hoy_local + timedelta(days=delta)
    return None


def parse_fecha_escrita(text, ahora_utc, dia_contexto=None):
    """Parsea 'mañana 15:00', 'lunes 3pm', '15/07 10:00', '9:30' (esta
    última solo con `dia_contexto`). Devuelve datetime UTC naive o None."""
    text = _normalizar(text)
    if not text:
        return None
    ahora_local = ahora_utc - EC_OFFSET
    hoy_local = ahora_local.date()
    dia = None
    dow_es_hoy = False

    m = _RE_FECHA_NUM.search(text)
    if m:
        dd, mes, yy = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (1 <= dd <= 31 and 1 <= mes <= 12):
            return None
        year = hoy_local.year
        if yy:
            year = int(yy) + (2000 if len(yy) == 2 else 0)
        try:
            dia = hoy_local.replace(year=year, month=mes, day=dd)
        except ValueError:
            return None
        if not yy and dia < hoy_local:
            # "05/01" escrito en diciembre = enero del año siguiente.
            dia = dia.replace(year=year + 1)
        text = text[:m.start()] + ' ' + text[m.end():]
    elif _RE_PASADO.search(text):
        dia = hoy_local + timedelta(days=2)
        text = _RE_PASADO.sub(' ', text)
    elif _RE_MANANA.search(text):
        dia = hoy_local + timedelta(days=1)
        text = _RE_MANANA.sub(' ', text)
    elif _RE_HOY.search(text):
        dia = hoy_local
        text = _RE_HOY.sub(' ', text)
    else:
        mdow = _RE_DOW.search(text)
        if mdow:
            delta = (_DOW[mdow.group(1)] - hoy_local.weekday()) % 7
            dia = hoy_local + timedelta(days=delta)
            dow_es_hoy = delta == 0
            text = text[:mdow.start()] + ' ' + text[mdow.end():]

    hora = _extraer_hora(text)
    if hora is None:
        return None
    if dia is None:
        if not dia_contexto:
            return None
        dia = dia_contexto

    local = datetime(dia.year, dia.month, dia.day, hora[0], hora[1])
    if dow_es_hoy and local <= ahora_local:
        # "miércoles 8:00" siendo miércoles 9:00 → el miércoles siguiente.
        local += timedelta(days=7)
    return local + EC_OFFSET
